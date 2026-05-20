"""FastAPI router for the 8-step setup wizard.

All endpoints require an authenticated session (session cookie set by the
login flow in app.py).  The wizard uses HTMX: forms post via hx-post, and
routes return HTML fragments when the HX-Request header is present.

Route summary:
  GET  /wizard                  — full wizard page (step 1)
  GET  /wizard/step/1           — step 1 fragment
  POST /wizard/step/1/test      — test DB connection, return result fragment
  POST /wizard/step/1/detect    — auto-detect from weewx.conf, return filled form
  POST /wizard/step/1           — save DB settings, return step 2 fragment
  GET  /wizard/step/2           — introspect schema, render step 2 fragment
  POST /wizard/step/2           — save column mapping, return step 3 fragment
  GET  /wizard/step/3           — read station identity, render step 3 fragment
  POST /wizard/step/3           — save station info, return step 4 fragment
  GET  /wizard/step/4           — provider selection, render step 4 fragment
  POST /wizard/step/4           — save provider choices, return step 5 fragment
  GET  /wizard/step/5           — API key entry, render step 5 fragment
  POST /wizard/step/5/test      — test one provider, return result fragment
  POST /wizard/step/5           — save keys, return step 6 fragment
  GET  /wizard/step/6           — topology selection, render step 6 fragment
  POST /wizard/step/6           — save topology, return step 7 fragment
  GET  /wizard/step/7           — bind address form, render step 7 fragment
  POST /wizard/step/7           — save binds, return step 8 fragment
  GET  /wizard/step/8           — review summary, render step 8 fragment
  POST /wizard/apply            — write config files, render completion page
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from weewx_clearskies_config.auth import COOKIE_NAME, SessionManager
from weewx_clearskies_config.wizard.config_writer import apply_wizard
from weewx_clearskies_config.wizard.db import (
    build_db_url,
    detect_from_weewx_conf,
    test_connection,
)
from weewx_clearskies_config.wizard.providers import (
    get_provider,
    providers_by_domain,
    recommend_providers,
    test_provider,
)
from weewx_clearskies_config.wizard.schema import introspect_schema
from weewx_clearskies_config.wizard.state import (
    WizardState,
    clear_wizard_state,
    get_wizard_state,
    save_wizard_state,
)
from weewx_clearskies_config.wizard.station import (
    lookup_timezone,
    station_from_weewx_conf,
)
from weewx_clearskies_config.wizard.topology import (
    generate_proxy_secret,
    topology_defaults,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wizard", tags=["wizard"])

# Templates are resolved at router creation time; the Jinja2Templates instance
# is set by create_wizard_router() so the caller can pass the correct path.
_templates: Jinja2Templates | None = None
_session_manager: SessionManager | None = None
_config_dir: Path | None = None


def create_wizard_router(
    templates: Jinja2Templates,
    session_manager: SessionManager,
    config_dir: Path,
) -> APIRouter:
    """Configure the wizard router with shared app objects and return it."""
    global _templates, _session_manager, _config_dir  # noqa: PLW0603
    _templates = templates
    _session_manager = session_manager
    _config_dir = config_dir
    return router


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_session_id(request: Request) -> str | None:
    """Extract a validated session ID from the request cookie."""
    if _session_manager is None:
        return None
    session_id = request.cookies.get(COOKIE_NAME, "")
    if not session_id or not _session_manager.get_username(session_id):
        return None
    return session_id


def _require_session(request: Request) -> str:
    """Return session_id or raise 401 if unauthenticated."""
    session_id = _get_session_id(request)
    if not session_id:
        raise _unauthorized()
    return session_id


def _unauthorized() -> Exception:
    # Wizard is an HTML UI; unauthenticated requests get a 401.  Browser
    # clients that receive it are redirected to /login by the HTMX response
    # error handler wired in layout.html.
    from starlette.exceptions import HTTPException as StarletteHTTPException
    return StarletteHTTPException(status_code=401, detail="Authentication required")


def _render(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    is_htmx: bool,  # kept for callers; both paths render the same fragment
    status_code: int = 200,
) -> HTMLResponse:
    """Render a wizard step fragment.

    Step templates are always fragments (no full-page wrapper here — the
    layout.html base wraps step 1 on initial load; subsequent steps are
    swapped into #wizard-content by HTMX).
    """
    assert _templates is not None, "Wizard router not initialised"
    return _templates.TemplateResponse(
        request=request,
        name=f"wizard/{template_name}",
        context=context,
        status_code=status_code,
    )


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


# ---------------------------------------------------------------------------
# Wizard entry point
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def wizard_index(request: Request) -> HTMLResponse:
    """Render the full wizard page with step 1 loaded."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/layout.html",
        context={"step": 1, "state": state},
    )


# ---------------------------------------------------------------------------
# Step 1: DB connection
# ---------------------------------------------------------------------------


@router.get("/step/1", response_class=HTMLResponse)
async def step1_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    return _render(
        request,
        "step_db.html",
        {"step": 1, "state": state, "result": None, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/1/test", response_class=HTMLResponse)
async def step1_test(request: Request) -> HTMLResponse:
    """Test the DB connection without saving; return a result fragment."""
    _require_session(request)
    form = await request.form()
    host = str(form.get("db_host", "localhost")).strip()
    port = _parse_int(str(form.get("db_port", "3306")), default=3306)
    user = str(form.get("db_user", "")).strip()
    password = str(form.get("db_password", ""))
    db_name = str(form.get("db_name", "weewx")).strip()

    result = test_connection(host, port, user, password, db_name)
    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/step_db.html",
        context={
            "step": 1,
            "state": WizardState(
                db_host=host,
                db_port=port,
                db_user=user,
                db_password=password,
                db_name=db_name,
            ),
            "result": result,
            "error": None if result["success"] else result.get("error"),
        },
    )


@router.post("/step/1/detect", response_class=HTMLResponse)
async def step1_detect(request: Request) -> HTMLResponse:
    """Auto-detect DB settings from weewx.conf; return populated form."""
    _require_session(request)
    form = await request.form()
    conf_path = str(form.get("conf_path", "/etc/weewx/weewx.conf")).strip()

    error: str | None = None
    detected: dict[str, Any] = {}
    try:
        detected = detect_from_weewx_conf(conf_path)
    except FileNotFoundError:
        error = f"weewx.conf not found at: {conf_path}"
    except (KeyError, ValueError) as exc:
        error = str(exc)

    assert _templates is not None
    state = WizardState(
        db_host=detected.get("host") or None,
        db_port=int(detected.get("port", 3306)),
        db_user=detected.get("user") or None,
        db_password=detected.get("password") or None,
        db_name=detected.get("db_name", "weewx"),
    )
    return _templates.TemplateResponse(
        request=request,
        name="wizard/step_db.html",
        context={"step": 1, "state": state, "result": None, "error": error},
    )


@router.post("/step/1", response_class=HTMLResponse)
async def step1_post(request: Request) -> HTMLResponse:
    """Save DB settings and advance to step 2."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)
    state.db_host = str(form.get("db_host", "")).strip() or None
    state.db_port = _parse_int(str(form.get("db_port", "3306")), default=3306)
    state.db_user = str(form.get("db_user", "")).strip() or None
    state.db_password = str(form.get("db_password", ""))
    state.db_name = str(form.get("db_name", "weewx")).strip() or "weewx"
    save_wizard_state(session_id, state)
    return await step2_get(request)


# ---------------------------------------------------------------------------
# Step 2: Schema + Column Mapping
# ---------------------------------------------------------------------------


@router.get("/step/2", response_class=HTMLResponse)
async def step2_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    schema_data: dict[str, Any] | None = None
    error: str | None = None

    if state.db_host and state.db_user:
        db_url = build_db_url(
            state.db_host,
            state.db_port,
            state.db_user,
            state.db_password or "",
            state.db_name,
        )
        try:
            schema_data = introspect_schema(db_url)
        except Exception as exc:  # noqa: BLE001
            error = f"Schema introspection failed: {exc}"
            logger.warning("Schema introspection error: %s", exc)

    return _render(
        request,
        "step_schema.html",
        {"step": 2, "state": state, "schema": schema_data, "error": error},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/2", response_class=HTMLResponse)
async def step2_post(request: Request) -> HTMLResponse:
    """Save column mapping choices and advance to step 3."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    # Form fields are named "col_<db_column_name>" for each unmapped column.
    mapping: dict[str, str | None] = {}
    for key, value in form.multi_items():
        if key.startswith("col_"):
            db_col = key[4:]  # strip "col_" prefix
            canonical = str(value).strip() or None
            mapping[db_col] = canonical

    state.column_mapping = mapping
    save_wizard_state(session_id, state)
    return await step3_get(request)


# ---------------------------------------------------------------------------
# Step 3: Station Identity
# ---------------------------------------------------------------------------


@router.get("/step/3", response_class=HTMLResponse)
async def step3_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    # Pre-fill from weewx.conf if station data not yet collected.
    if state.station_name is None:
        for conf_path in _weewx_conf_candidates():
            try:
                detected = station_from_weewx_conf(conf_path)
                state.station_name = detected.get("station_name")
                state.latitude = _to_float(detected.get("latitude"))
                state.longitude = _to_float(detected.get("longitude"))
                state.altitude_meters = _to_float(detected.get("altitude_meters"))
                if state.latitude and state.longitude and not state.timezone:
                    state.timezone = lookup_timezone(state.latitude, state.longitude)
                break
            except (FileNotFoundError, KeyError):
                continue

    return _render(
        request,
        "step_station.html",
        {"step": 3, "state": state, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/3", response_class=HTMLResponse)
async def step3_post(request: Request) -> HTMLResponse:
    """Save station identity and advance to step 4."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    state.station_name = str(form.get("station_name", "")).strip() or None
    state.latitude = _to_float(form.get("latitude"))
    state.longitude = _to_float(form.get("longitude"))
    state.altitude_meters = _to_float(form.get("altitude_meters"))
    state.timezone = str(form.get("timezone", "")).strip() or None

    # Auto-lookup timezone if coordinates provided but timezone not set.
    if state.latitude and state.longitude and not state.timezone:
        state.timezone = lookup_timezone(state.latitude, state.longitude)

    save_wizard_state(session_id, state)
    return await step4_get(request)


# ---------------------------------------------------------------------------
# Step 4: Provider Selection
# ---------------------------------------------------------------------------


@router.get("/step/4", response_class=HTMLResponse)
async def step4_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    by_domain = providers_by_domain()
    recommendations: dict[str, str] = {}
    if state.latitude is not None and state.longitude is not None:
        recommendations = recommend_providers(state.latitude, state.longitude)

    return _render(
        request,
        "step_providers.html",
        {
            "step": 4,
            "state": state,
            "providers_by_domain": by_domain,
            "recommendations": recommendations,
            "error": None,
        },
        is_htmx=_is_htmx(request),
    )


@router.post("/step/4", response_class=HTMLResponse)
async def step4_post(request: Request) -> HTMLResponse:
    """Save provider selections and advance to step 5."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    providers: dict[str, str] = {}
    for domain in ("forecast", "alerts", "aqi", "earthquakes", "radar"):
        provider_id = str(form.get(f"provider_{domain}", "")).strip()
        if provider_id:
            providers[domain] = provider_id
    state.providers = providers
    save_wizard_state(session_id, state)
    return await step5_get(request)


# ---------------------------------------------------------------------------
# Step 5: API Keys
# ---------------------------------------------------------------------------


@router.get("/step/5", response_class=HTMLResponse)
async def step5_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    # Collect providers that require credentials.
    keyed_providers = []
    for provider_id in state.providers.values():
        info = get_provider(provider_id)
        if info and info.auth_fields:
            keyed_providers.append(info)

    # De-duplicate (same provider in multiple domains)
    seen: set[str] = set()
    unique_keyed: list[Any] = []
    for p in keyed_providers:
        if p.provider_id not in seen:
            unique_keyed.append(p)
            seen.add(p.provider_id)

    return _render(
        request,
        "step_keys.html",
        {"step": 5, "state": state, "keyed_providers": unique_keyed, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/5/test", response_class=HTMLResponse)
async def step5_test(request: Request) -> HTMLResponse:
    """Test one provider's connectivity; return a result fragment."""
    _require_session(request)
    form = await request.form()
    provider_id = str(form.get("provider_id", "")).strip()
    info = get_provider(provider_id)

    if not info:
        assert _templates is not None
        return _templates.TemplateResponse(
            request=request,
            name="wizard/step_keys.html",
            context={
                "step": 5,
                "test_result": {"success": False, "error": f"Unknown provider: {provider_id}"},
                "test_provider_id": provider_id,
            },
        )

    credentials: dict[str, str] = {}
    for field_name in info.auth_fields:
        credentials[field_name] = str(form.get(field_name, "")).strip()

    result = test_provider(info, credentials)
    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/step_keys.html",
        context={
            "step": 5,
            "test_result": result,
            "test_provider_id": provider_id,
            "test_provider_name": info.display_name,
        },
    )


@router.post("/step/5", response_class=HTMLResponse)
async def step5_post(request: Request) -> HTMLResponse:
    """Save API keys and advance to step 6."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    api_keys: dict[str, dict[str, str]] = {}
    for provider_id in state.providers.values():
        info = get_provider(provider_id)
        if info and info.auth_fields:
            creds: dict[str, str] = {}
            for field_name in info.auth_fields:
                value = str(form.get(f"{provider_id}_{field_name}", "")).strip()
                if value:
                    creds[field_name] = value
            if creds:
                api_keys[provider_id] = creds

    state.api_keys = api_keys
    save_wizard_state(session_id, state)
    return await step6_get(request)


# ---------------------------------------------------------------------------
# Step 6: Topology
# ---------------------------------------------------------------------------


@router.get("/step/6", response_class=HTMLResponse)
async def step6_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    defaults = topology_defaults(same_host=(state.topology == "same-host"))
    return _render(
        request,
        "step_topology.html",
        {"step": 6, "state": state, "defaults": defaults, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/6", response_class=HTMLResponse)
async def step6_post(request: Request) -> HTMLResponse:
    """Save topology choice and advance to step 7."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    topology = str(form.get("topology", "same-host")).strip()
    if topology not in ("same-host", "cross-host"):
        topology = "same-host"
    state.topology = topology

    if topology == "cross-host" and not state.proxy_secret:
        state.proxy_secret = generate_proxy_secret()

    # Apply topology-based address defaults before rendering step 7.
    td = topology_defaults(same_host=(topology == "same-host"))
    state.api_bind_host = td["api_bind_host"]
    state.realtime_bind_host = td["realtime_bind_host"]

    save_wizard_state(session_id, state)
    return await step7_get(request)


# ---------------------------------------------------------------------------
# Step 7: Bind Addresses
# ---------------------------------------------------------------------------


@router.get("/step/7", response_class=HTMLResponse)
async def step7_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    return _render(
        request,
        "step_binds.html",
        {"step": 7, "state": state, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/step/7", response_class=HTMLResponse)
async def step7_post(request: Request) -> HTMLResponse:
    """Save bind addresses and advance to step 8."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    state.api_bind_host = str(form.get("api_bind_host", "127.0.0.1")).strip()
    state.api_bind_port = _parse_int(str(form.get("api_bind_port", "8765")), default=8765)
    state.realtime_bind_host = str(form.get("realtime_bind_host", "127.0.0.1")).strip()
    state.realtime_bind_port = _parse_int(
        str(form.get("realtime_bind_port", "8766")), default=8766
    )

    save_wizard_state(session_id, state)
    return await step8_get(request)


# ---------------------------------------------------------------------------
# Step 8: Review + Apply
# ---------------------------------------------------------------------------


@router.get("/step/8", response_class=HTMLResponse)
async def step8_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    return _render(
        request,
        "step_review.html",
        {"step": 8, "state": state, "error": None},
        is_htmx=_is_htmx(request),
    )


@router.post("/apply", response_class=HTMLResponse)
async def wizard_apply(request: Request) -> HTMLResponse:
    """Write config files and display the completion page."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    if _config_dir is None:
        assert _templates is not None
        return _templates.TemplateResponse(
            request=request,
            name="wizard/step_complete.html",
            context={
                "step": 8,
                "error": "Config directory is not configured. Cannot write files.",
                "result": None,
            },
            status_code=500,
        )

    error: str | None = None
    result: dict[str, Any] | None = None
    try:
        result = apply_wizard(state, _config_dir)
        clear_wizard_state(session_id)
    except OSError as exc:
        error = f"Failed to write config files: {exc}"
        logger.error("apply_wizard OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error during config write: {exc}"
        logger.exception("apply_wizard unexpected error")

    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/step_complete.html",
        context={"step": 8, "error": error, "result": result},
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _weewx_conf_candidates() -> list[str]:
    """Return common weewx.conf paths to probe for auto-detection."""
    return [
        "/etc/weewx/weewx.conf",
        "/home/weewx/weewx.conf",
        "/opt/weewx/weewx.conf",
    ]

"""FastAPI router for the 6-step setup wizard.

All endpoints require an authenticated session (session cookie set by the
login flow in app.py).  The wizard uses HTMX: forms post via hx-post, and
routes return HTML fragments when the HX-Request header is present.

Route summary:
  GET  /wizard                  — full wizard page (step 1)
  GET  /wizard/step/1           — step 1 fragment
  POST /wizard/step/1/test      — test DB connection, return result fragment
  POST /wizard/step/1/detect    — auto-detect from weewx.conf, return filled form
  POST /wizard/step/1           — save DB settings, return step 2 or 3 fragment
  GET  /wizard/step/2           — introspect schema, render step 2 fragment
  POST /wizard/step/2           — save column mapping, return step 3 fragment
  GET  /wizard/step/3           — read station identity, render step 3 fragment
  POST /wizard/step/3/timezone  — lookup timezone from lat/lon, return input fragment
  POST /wizard/step/3/detect-weewx — detect station from local weewx.conf
  POST /wizard/step/3           — save station info, return step 4 fragment
  GET  /wizard/step/4           — data pipeline / MQTT, render step 4 fragment
  POST /wizard/step/4/test      — test MQTT broker connection, return result fragment
  POST /wizard/step/4           — save input mode + MQTT settings, return step 5 fragment
  GET  /wizard/step/5           — provider selection + inline key entry, render step 5 fragment
  GET  /wizard/step/5/key-fields/{domain}/{provider_id} — inline key fields fragment
  POST /wizard/step/5/test-key/{provider_id}            — test one provider's key, return result fragment
  POST /wizard/step/5           — save provider choices + keys, return step 6 fragment
  GET  /wizard/step/6           — review summary, render step 6 fragment
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
    configure_state_persistence,
    get_wizard_state,
    save_wizard_state,
)
from weewx_clearskies_config.wizard.station import (
    lookup_timezone,
    station_from_api,
    station_from_weewx_conf,
)
from weewx_clearskies_config.wizard.topology import generate_proxy_secret

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
    configure_state_persistence(config_dir)
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
    if state.db_host is None:
        _merge_from_existing_config(state)
    return _render(
        request,
        "step_db.html",
        {"step": 1, "state": state, "result": None, "error": None},
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
    return _render(
        request,
        "step_db_test_result.html",
        {"result": result},
    )


@router.post("/step/1/detect", response_class=HTMLResponse)
async def step1_detect(request: Request) -> HTMLResponse:
    """Auto-detect DB settings from weewx.conf; return populated form."""
    _require_session(request)
    form = await request.form()
    conf_path = str(form.get("conf_path", "/etc/weewx/weewx.conf")).strip()

    _ALLOWED_CONF_PREFIXES = ("/etc/weewx/", "/home/weewx/", "/usr/share/weewx/")
    # Resolve symlinks and `../` traversal before checking the allowed-prefix
    # list.  Without this, a path like `/etc/weewx/../../etc/shadow` passes the
    # naive startswith check.
    try:
        resolved = str(Path(conf_path).resolve())
    except (OSError, ValueError):
        resolved = ""
    if not any(resolved.startswith(p) for p in _ALLOWED_CONF_PREFIXES):
        conf_path = "/etc/weewx/weewx.conf"
    else:
        conf_path = resolved

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
    """Save DB settings, auto-detect topology/binds/schema, advance to step 2 or 3."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)
    state.db_host = str(form.get("db_host", "")).strip() or None
    state.db_port = _parse_int(str(form.get("db_port", "3306")), default=3306)
    state.db_user = str(form.get("db_user", "")).strip() or None
    state.db_password = str(form.get("db_password", ""))
    state.db_name = str(form.get("db_name", "weewx")).strip() or "weewx"

    # Auto-detect topology from DB host: loopback → same-host, anything else → cross-host.
    _LOOPBACK = {"localhost", "127.0.0.1", "::1"}
    if (state.db_host or "").lower() in _LOOPBACK:
        state.topology = "same-host"
        state.api_bind_host = "127.0.0.1"
        state.realtime_bind_host = "127.0.0.1"
    else:
        state.topology = "cross-host"
        if not state.proxy_secret:
            state.proxy_secret = generate_proxy_secret()
        state.api_bind_host = "::"
        state.realtime_bind_host = "::"
    state.api_bind_port = 8765
    state.realtime_bind_port = 8766

    # Introspect schema now so we can skip step 2 if there are no unmapped columns.
    skip_schema = False
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
            if not schema_data.get("unmapped_columns"):
                # All columns are stock; auto-save the stock mapping and skip step 2.
                state.column_mapping = {
                    col["db_name"]: col["canonical"]
                    for col in schema_data.get("stock_columns", [])
                }
                skip_schema = True
        except Exception:  # noqa: BLE001
            # If introspection fails, fall through to show step 2 so the user
            # can address the connection issue or review manually.
            logger.warning("Schema introspection failed in step1_post; showing step 2", exc_info=True)

    save_wizard_state(session_id, state)
    if skip_schema:
        return await step3_get(request)
    return await step2_get(request)


# ---------------------------------------------------------------------------
# Step 4: Data Pipeline (input mode / MQTT)
# ---------------------------------------------------------------------------


@router.get("/step/4", response_class=HTMLResponse)
async def step4_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    return _render(
        request,
        "step_mqtt.html",
        {"step": 4, "state": state, "error": None, "test_result": None},
    )


@router.post("/step/4/test", response_class=HTMLResponse)
async def step4_mqtt_test(request: Request) -> HTMLResponse:
    """Test MQTT broker reachability without saving; return a result fragment."""
    _require_session(request)
    form = await request.form()
    host = str(form.get("mqtt_broker_host", "")).strip()
    port = _parse_int(str(form.get("mqtt_broker_port", "1883")), default=1883)
    username = str(form.get("mqtt_username", "")).strip()
    password = str(form.get("mqtt_password", ""))
    tls = str(form.get("mqtt_tls", "false")).lower() in ("true", "on", "1", "yes")

    result = _test_mqtt_connection(host, port, username, password, tls)
    return _render(
        request,
        "step_mqtt_test_result.html",
        {"result": result},
    )


@router.post("/step/4", response_class=HTMLResponse)
async def step4_post(request: Request) -> HTMLResponse:
    """Save input mode + MQTT settings and advance to step 5 (providers)."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    state.input_mode = str(form.get("input_mode", "direct")).strip()
    if state.input_mode not in ("direct", "mqtt"):
        state.input_mode = "direct"

    if state.input_mode == "mqtt":
        state.mqtt_broker_host = str(form.get("mqtt_broker_host", "")).strip()
        port_raw = _parse_int(str(form.get("mqtt_broker_port", "1883")), default=1883)
        state.mqtt_broker_port = max(1, min(65535, port_raw))
        state.mqtt_topic = str(form.get("mqtt_topic", "weewx/loop")).strip() or "weewx/loop"
        state.mqtt_client_id = (
            str(form.get("mqtt_client_id", "weewx-clearskies-realtime")).strip()
            or "weewx-clearskies-realtime"
        )
        state.mqtt_username = str(form.get("mqtt_username", "")).strip()
        state.mqtt_password = str(form.get("mqtt_password", ""))
        state.mqtt_tls = str(form.get("mqtt_tls", "false")).lower() in ("true", "on", "1", "yes")
        qos_raw = _parse_int(str(form.get("mqtt_qos", "0")), default=0)
        state.mqtt_qos = qos_raw if qos_raw in (0, 1, 2) else 0
        keepalive_raw = _parse_int(str(form.get("mqtt_keepalive", "60")), default=60)
        state.mqtt_keepalive = max(1, keepalive_raw)

        errors = _validate_mqtt_settings(state)
        if errors:
            return _render(
                request,
                "step_mqtt.html",
                {"step": 4, "state": state, "error": "; ".join(errors.values()), "test_result": None},
                status_code=422,
            )

    save_wizard_state(session_id, state)
    return await step5_get(request)


# ---------------------------------------------------------------------------
# Step 2: Schema + Column Mapping
# ---------------------------------------------------------------------------


@router.get("/step/2", response_class=HTMLResponse)
async def step2_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    if not state.column_mapping:
        _merge_from_existing_config(state)

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
        {"step": 2, "state": state, "schema": schema_data, "error": error, "errors": {}},
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

    errors = _validate_column_mapping(mapping)
    if errors:
        schema_data: dict[str, Any] | None = None
        schema_error: str | None = None
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
                schema_error = f"Schema introspection failed: {exc}"
                logger.warning("Schema introspection error in step2_post: %s", exc)
        return _render(
            request,
            "step_schema.html",
            {
                "step": 2,
                "state": state,
                "schema": schema_data,
                "error": schema_error,
                "errors": errors,
            },
            status_code=422,
        )

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

    # Try to pre-fill from the API only when station fields are empty.
    if state.station_name is None and state.db_host:
        api_data = station_from_api(state.db_host)
        if api_data:
            if state.station_name is None:
                state.station_name = api_data.get("station_name")
            if state.latitude is None:
                state.latitude = _to_float(api_data.get("latitude"))
            if state.longitude is None:
                state.longitude = _to_float(api_data.get("longitude"))
            if state.altitude_meters is None:
                state.altitude_meters = _to_float(api_data.get("altitude_meters"))
            if state.timezone is None and api_data.get("timezone"):
                state.timezone = api_data["timezone"]
            if state.latitude and state.longitude and not state.timezone:
                state.timezone = lookup_timezone(state.latitude, state.longitude)

    if state.station_name is None:
        _merge_from_existing_config(state)

    return _render(
        request,
        "step_station.html",
        {"step": 3, "state": state, "error": None},
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

    # Altitude is always stored in meters internally.  The form includes an
    # altitude_unit field ("feet" or "meters") so we can convert as needed.
    alt_raw = _to_float(form.get("altitude_meters"))
    alt_unit = str(form.get("altitude_unit", "meters")).strip().lower()
    if alt_raw is not None and ("foot" in alt_unit or "feet" in alt_unit or "ft" in alt_unit):
        state.altitude_meters = alt_raw * 0.3048
    else:
        state.altitude_meters = alt_raw

    state.timezone = str(form.get("timezone", "")).strip() or None

    # Auto-lookup timezone if coordinates provided but timezone not set.
    if state.latitude and state.longitude and not state.timezone:
        state.timezone = lookup_timezone(state.latitude, state.longitude)

    save_wizard_state(session_id, state)
    return await step4_get(request)


@router.post("/step/3/timezone", response_class=HTMLResponse)
async def step3_timezone(request: Request) -> HTMLResponse:
    """Return a pre-filled timezone input fragment for the given lat/lon.

    Called by HTMX when the user changes the latitude or longitude fields.
    Responds with a replacement <input> element so HTMX can swap it directly
    into the DOM.
    """
    _require_session(request)
    form = await request.form()
    lat = _to_float(form.get("latitude"))
    lon = _to_float(form.get("longitude"))

    tz: str = ""
    if lat is not None and lon is not None:
        detected = lookup_timezone(lat, lon)
        if detected:
            tz = detected

    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/fragment_timezone_input.html",
        context={"timezone": tz},
    )


@router.post("/step/3/detect-weewx", response_class=HTMLResponse)
async def step3_detect_weewx(request: Request) -> HTMLResponse:
    """Read weewx.conf from the local host and return a pre-filled step 3 fragment.

    Only works when this tool runs on the weewx host.  On failure, returns the
    step 3 template with an error message so the user can fill fields manually.
    """
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    error: str | None = None
    for conf_path in _weewx_conf_candidates():
        try:
            detected = station_from_weewx_conf(conf_path)
            state.station_name = detected.get("station_name") or state.station_name
            lat = _to_float(detected.get("latitude"))
            lon = _to_float(detected.get("longitude"))
            alt = _to_float(detected.get("altitude_meters"))
            if lat is not None:
                state.latitude = lat
            if lon is not None:
                state.longitude = lon
            if alt is not None:
                state.altitude_meters = alt
            if state.latitude and state.longitude and not state.timezone:
                state.timezone = lookup_timezone(state.latitude, state.longitude)
            error = None
            break
        except FileNotFoundError:
            continue
        except (KeyError, ValueError) as exc:
            error = str(exc)
            break

    if error is None and state.station_name is None:
        error = "weewx.conf not found in standard locations."

    return _render(
        request,
        "step_station.html",
        {"step": 3, "state": state, "error": error},
    )


# ---------------------------------------------------------------------------
# Step 5: Provider Selection + Inline API Key Entry
# ---------------------------------------------------------------------------


@router.get("/step/5", response_class=HTMLResponse)
async def step5_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    if not state.providers:
        _merge_from_existing_config(state)

    by_domain = providers_by_domain()
    recommendations: dict[str, str] = {}
    if state.latitude is not None and state.longitude is not None:
        recommendations = recommend_providers(state.latitude, state.longitude)

    return _render(
        request,
        "step_providers.html",
        {
            "step": 5,
            "state": state,
            "providers_by_domain": by_domain,
            "recommendations": recommendations,
            "error": None,
        },
    )


@router.get("/step/5/key-fields/{domain}/{provider_id}", response_class=HTMLResponse)
async def step5_key_fields(request: Request, domain: str, provider_id: str) -> HTMLResponse:
    """Return inline key input fields for a provider that requires credentials."""
    session_id = _require_session(request)
    info = get_provider(provider_id)
    if not info or not info.auth_fields:
        assert _templates is not None
        return HTMLResponse(content="", status_code=200)

    state = get_wizard_state(session_id)

    return _render(
        request,
        "step_provider_key_fields.html",
        {"provider": info, "state": state},
    )


@router.post("/step/5/test-key/{provider_id}", response_class=HTMLResponse)
async def step5_test_key(request: Request, provider_id: str) -> HTMLResponse:
    """Test one provider's API key; return a result fragment."""
    _require_session(request)
    form = await request.form()
    info = get_provider(provider_id)

    if not info:
        return _render(
            request,
            "step_provider_test_result.html",
            {
                "test_result": {"success": False, "error": f"Unknown provider: {provider_id}"},
                "test_provider_id": provider_id,
                "test_provider_name": provider_id,
            },
        )

    credentials: dict[str, str] = {}
    for field_name in info.auth_fields:
        credentials[field_name] = str(form.get(f"{provider_id}_{field_name}", "")).strip()

    result = test_provider(info, credentials)
    return _render(
        request,
        "step_provider_test_result.html",
        {
            "test_result": result,
            "test_provider_id": provider_id,
            "test_provider_name": info.display_name,
        },
    )


@router.post("/step/5", response_class=HTMLResponse)
async def step5_post(request: Request) -> HTMLResponse:
    """Save provider selections and inline API keys, advance to step 6."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    providers: dict[str, str] = {}
    for domain in ("forecast", "alerts", "aqi", "earthquakes", "radar"):
        provider_id = str(form.get(f"provider_{domain}", "")).strip()
        if provider_id:
            providers[domain] = provider_id
    state.providers = providers

    # Collect inline API keys submitted alongside the provider selection.
    # Form fields are namespaced "{provider_id}_{field_name}".
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
# Step 6: Review + Apply
# ---------------------------------------------------------------------------


@router.get("/step/6", response_class=HTMLResponse)
async def step6_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    if state.db_host is None and state.station_name is None:
        _merge_from_existing_config(state)
    return _render(
        request,
        "step_review.html",
        {"step": 6, "state": state, "error": None},
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
                "step": 6,
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
        context={"step": 6, "error": error, "result": result},
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# Column mapping validation
# ---------------------------------------------------------------------------


def _validate_column_mapping(mapping: dict[str, str | None]) -> dict[str, str]:
    """Validate the column mapping submitted from step 2.

    Checks:
    - No two DB columns may map to the same canonical name (duplicate).
    - Each non-blank canonical name must exist in the known field registry.

    Returns a dict of ``{db_column_name: error_message}`` for each offending
    column.  An empty dict means the mapping is valid.
    """
    try:
        from weewx_clearskies_api.db.reflection import STOCK_COLUMN_MAP  # type: ignore[import-untyped]
        valid_canonicals: set[str] = set(STOCK_COLUMN_MAP.values())
    except Exception:  # noqa: BLE001
        # If the API package is unavailable, skip canonical name validation
        # so the wizard remains functional without it.
        valid_canonicals = set()

    errors: dict[str, str] = {}

    # Duplicate-canonical check: build reverse map of canonical → [db_col, ...]
    seen: dict[str, list[str]] = {}
    for db_col, canonical in mapping.items():
        if canonical:
            seen.setdefault(canonical, []).append(db_col)
    for canonical, db_cols in seen.items():
        if len(db_cols) > 1:
            for db_col in db_cols:
                errors[db_col] = f'"{canonical}" is used by multiple columns — each canonical name must be unique.'

    # Unknown canonical name check
    if valid_canonicals:
        for db_col, canonical in mapping.items():
            if canonical and canonical not in valid_canonicals and db_col not in errors:
                errors[db_col] = f'"{canonical}" is not a recognised canonical field name.'

    return errors


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


def _existing_configs_present() -> bool:
    """Return True if api.conf exists in config_dir (wizard has run before)."""
    if _config_dir is None:
        return False
    return (_config_dir / "api.conf").exists()


def _merge_from_existing_config(state: WizardState) -> None:
    """Merge fields from existing config files into *state* for any empty fields.

    Only fills fields that are still at their default/empty values so user edits
    made during the current wizard run are never overwritten.
    """
    if not _existing_configs_present():
        return
    from weewx_clearskies_config.wizard.state_persistence import populate_from_config
    assert _config_dir is not None
    try:
        existing = populate_from_config(_config_dir)
    except Exception:  # noqa: BLE001
        logger.warning("populate_from_config failed; skipping pre-populate", exc_info=True)
        return

    if state.db_host is None and existing.db_host is not None:
        state.db_host = existing.db_host
    if state.db_port == 3306 and existing.db_port != 3306:
        state.db_port = existing.db_port
    if state.db_user is None and existing.db_user is not None:
        state.db_user = existing.db_user
    if state.db_password is None and existing.db_password is not None:
        state.db_password = existing.db_password
    if state.db_name == "weewx" and existing.db_name != "weewx":
        state.db_name = existing.db_name

    if not state.column_mapping and existing.column_mapping:
        state.column_mapping = existing.column_mapping

    if state.station_name is None and existing.station_name is not None:
        state.station_name = existing.station_name
    if state.latitude is None and existing.latitude is not None:
        state.latitude = existing.latitude
    if state.longitude is None and existing.longitude is not None:
        state.longitude = existing.longitude
    if state.altitude_meters is None and existing.altitude_meters is not None:
        state.altitude_meters = existing.altitude_meters
    if state.timezone is None and existing.timezone is not None:
        state.timezone = existing.timezone

    if not state.providers and existing.providers:
        state.providers = existing.providers

    if not state.api_keys and existing.api_keys:
        state.api_keys = existing.api_keys

    if state.topology == "same-host" and existing.topology != "same-host":
        state.topology = existing.topology
    if state.proxy_secret is None and existing.proxy_secret is not None:
        state.proxy_secret = existing.proxy_secret

    if state.api_bind_host == "127.0.0.1" and existing.api_bind_host != "127.0.0.1":
        state.api_bind_host = existing.api_bind_host
    if state.api_bind_port == 8765 and existing.api_bind_port != 8765:
        state.api_bind_port = existing.api_bind_port
    if state.realtime_bind_host == "127.0.0.1" and existing.realtime_bind_host != "127.0.0.1":
        state.realtime_bind_host = existing.realtime_bind_host
    if state.realtime_bind_port == 8766 and existing.realtime_bind_port != 8766:
        state.realtime_bind_port = existing.realtime_bind_port

    if state.input_mode == "direct" and existing.input_mode != "direct":
        state.input_mode = existing.input_mode
    if not state.mqtt_broker_host and existing.mqtt_broker_host:
        state.mqtt_broker_host = existing.mqtt_broker_host
    if state.mqtt_broker_port == 1883 and existing.mqtt_broker_port != 1883:
        state.mqtt_broker_port = existing.mqtt_broker_port
    if state.mqtt_topic == "weewx/loop" and existing.mqtt_topic != "weewx/loop":
        state.mqtt_topic = existing.mqtt_topic
    if state.mqtt_client_id == "weewx-clearskies-realtime" and existing.mqtt_client_id != "weewx-clearskies-realtime":
        state.mqtt_client_id = existing.mqtt_client_id
    if not state.mqtt_username and existing.mqtt_username:
        state.mqtt_username = existing.mqtt_username
    if not state.mqtt_password and existing.mqtt_password:
        state.mqtt_password = existing.mqtt_password
    if not state.mqtt_tls and existing.mqtt_tls:
        state.mqtt_tls = existing.mqtt_tls


def _validate_mqtt_settings(state: WizardState) -> dict[str, str]:
    """Validate MQTT fields when input_mode is 'mqtt'.

    Returns a dict of {field_name: error_message}.  Empty dict = valid.
    """
    errors: dict[str, str] = {}
    if not state.mqtt_broker_host:
        errors["mqtt_broker_host"] = "Broker host is required when MQTT mode is selected."
    if not (1 <= state.mqtt_broker_port <= 65535):
        errors["mqtt_broker_port"] = "Broker port must be between 1 and 65535."
    if state.mqtt_qos not in (0, 1, 2):
        errors["mqtt_qos"] = "QoS must be 0, 1, or 2."
    return errors


def _test_mqtt_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    tls: bool,
) -> dict[str, Any]:
    """Attempt a socket-level connection to the MQTT broker.

    Uses a raw TCP connect rather than importing paho-mqtt so we don't
    depend on the broker package being present in the config tool's venv.
    A successful TCP handshake proves the host:port is reachable; full MQTT
    auth is not verified here (that would require paho or similar).

    Returns: {"success": bool, "error": str | None, "note": str | None}
    """
    import socket

    if not host:
        return {"success": False, "error": "Broker host is required.", "note": None}

    # Resolve to all address families so IPv6 brokers work too.
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return {"success": False, "error": f"DNS resolution failed: {exc}", "note": None}

    last_error: str = "No addresses resolved."
    for family, sock_type, proto, _canonname, sockaddr in addr_infos:
        try:
            with socket.socket(family, sock_type, proto) as sock:
                sock.settimeout(5)
                sock.connect(sockaddr)
            note = "TCP connection succeeded. MQTT credentials are not verified here."
            return {"success": True, "error": None, "note": note}
        except OSError as exc:
            last_error = str(exc)

    return {"success": False, "error": f"Connection refused or timed out: {last_error}", "note": None}

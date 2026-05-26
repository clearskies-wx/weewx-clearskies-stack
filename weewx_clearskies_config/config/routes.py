"""FastAPI router for the master configuration page.

Provides per-section CRUD endpoints so operators can edit settings after the
initial setup wizard.  Changes are merged into the MANAGED REGION of the
relevant .conf file, leaving operator-added free-form content intact.

Route summary:
  GET  /admin/config                          — config dashboard (all sections)
  GET  /admin/config/{component}/{section}    — section edit form fragment
  POST /admin/config/{component}/{section}    — save section, return result fragment
  GET  /admin/config/column-mapping           — column mapping form
  POST /admin/config/column-mapping           — update column mapping, return result
  POST /admin/config/test-provider            — test provider connectivity
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from weewx_clearskies_config.auth import COOKIE_NAME, SessionManager
from weewx_clearskies_config.config.reader import (
    get_all_sections,
    get_column_mapping,
    get_section,
)
from weewx_clearskies_config.config.updater import (
    update_column_mapping,
    update_managed_region,
    update_secrets,
)
from weewx_clearskies_config.wizard.providers import get_provider, test_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section metadata: which sections are editable, per component
# ---------------------------------------------------------------------------

# Each entry: (component, section_key, display_name, secret_fields)
# secret_fields: form field names whose values go into secrets.env instead of
# being written directly into the .conf file.
_SECTION_META: list[tuple[str, str, str, tuple[str, ...]]] = [
    # api.conf sections
    ("api", "server", "API Server", ()),
    ("api", "database", "Database Connection", ("password",)),
    ("api", "forecast", "Forecast Provider", ()),
    ("api", "alerts", "Alerts Provider", ()),
    ("api", "aqi", "AQI Provider", ()),
    ("api", "earthquakes", "Earthquakes Provider", ()),
    ("api", "radar", "Radar Provider", ()),
    # realtime.conf sections
    ("realtime", "server", "Realtime Server", ()),
    ("realtime", "mqtt", "MQTT Settings", ("password",)),
    # stack.conf sections
    ("stack", "ui", "UI Settings", ()),
]

# Set of (component, section) pairs that are valid for editing
_VALID_SECTIONS: frozenset[tuple[str, str]] = frozenset(
    (comp, sec) for comp, sec, _name, _secrets in _SECTION_META
)

# Allowed keys per (component, section).  Only these keys are accepted from
# form submissions — any extra keys are silently dropped (input validation at
# trust boundary per coding.md §1).
_SECTION_ALLOWED_KEYS: dict[tuple[str, str], frozenset[str]] = {
    ("api", "server"):      frozenset({"bind_host", "bind_port"}),
    ("api", "database"):    frozenset({"host", "port", "user", "name", "password"}),
    ("api", "forecast"):    frozenset({"provider"}),
    ("api", "alerts"):      frozenset({"provider"}),
    ("api", "aqi"):         frozenset({"provider"}),
    ("api", "earthquakes"): frozenset({"provider"}),
    ("api", "radar"):       frozenset({"provider"}),
    ("realtime", "server"): frozenset({"bind_host", "bind_port"}),
    ("realtime", "mqtt"):   frozenset({
        "enabled", "broker_host", "broker_port", "topic", "username", "password",
        # Also accept legacy keys written by the wizard
        "broker", "port",
    }),
    ("stack", "ui"):        frozenset({
        "enabled", "bind_host", "bind_port", "tls_cert_path", "tls_key_path",
        "station_name", "latitude", "longitude", "altitude_meters", "timezone",
        "topology",
    }),
}

# Map (component, section) -> display name
_SECTION_DISPLAY: dict[tuple[str, str], str] = {
    (comp, sec): name for comp, sec, name, _secrets in _SECTION_META
}

# Map (component, section) -> tuple of secret field names
_SECTION_SECRETS: dict[tuple[str, str], tuple[str, ...]] = {
    (comp, sec): secrets for comp, sec, _name, secrets in _SECTION_META
}

# Map secret field name -> secrets.env key prefix
# Actual env key is WEEWX_CLEARSKIES_<COMPONENT>_<SECTION>_<FIELD>.upper()
# Built dynamically in the route handler.

# Canonical field names available for column mapping
# Sourced from the weewx standard schema; surfaced as datalist options in the UI.
_CANONICAL_FIELDS = (
    "dateTime",
    "usUnits",
    "interval",
    "barometer",
    "pressure",
    "altimeter",
    "inTemp",
    "outTemp",
    "inHumidity",
    "outHumidity",
    "windSpeed",
    "windDir",
    "windGust",
    "windGustDir",
    "rain",
    "rainRate",
    "dewpoint",
    "windchill",
    "heatindex",
    "ET",
    "radiation",
    "UV",
    "extraTemp1",
    "extraTemp2",
    "extraTemp3",
    "soilTemp1",
    "soilTemp2",
    "soilTemp3",
    "soilTemp4",
    "leafTemp1",
    "leafTemp2",
    "extraHumid1",
    "extraHumid2",
    "soilMoist1",
    "soilMoist2",
    "soilMoist3",
    "soilMoist4",
    "leafWet1",
    "leafWet2",
    "rxCheckPercent",
    "txBatteryStatus",
    "consBatteryVoltage",
    "hail",
    "hailRate",
    "heatingTemp",
    "heatingVoltage",
    "supplyVoltage",
    "referenceVoltage",
    "windBatteryStatus",
    "rainBatteryStatus",
    "outTempBatteryStatus",
    "inTempBatteryStatus",
    "lightning_strike_count",
    "lightning_distance",
    "pm1_0",
    "pm2_5",
    "pm10_0",
    "co2",
)


# Module-level state injected by create_config_router()
_templates: Jinja2Templates | None = None
_session_manager: SessionManager | None = None
_config_dir: Path | None = None

router = APIRouter(prefix="/admin/config", tags=["config"])


def create_config_router(
    templates: Jinja2Templates,
    session_manager: SessionManager,
    config_dir: Path,
) -> APIRouter:
    """Configure the config router with shared app objects and return it."""
    global _templates, _session_manager, _config_dir  # noqa: PLW0603
    _templates = templates
    _session_manager = session_manager
    _config_dir = config_dir
    return router


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_session(request: Request) -> None:
    """Raise 401 if the request does not carry a valid session cookie."""
    mgr = _session_manager
    if mgr is None:
        _raise_unauthorized()
    session_id = request.cookies.get(COOKIE_NAME, "")
    if not session_id or not mgr.get_username(session_id):
        _raise_unauthorized()


def _raise_unauthorized() -> NoReturn:
    from starlette.exceptions import HTTPException as StarletteHTTPException
    raise StarletteHTTPException(status_code=401, detail="Authentication required")


def _render(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    assert _templates is not None, "Config router not initialised"
    return _templates.TemplateResponse(
        request=request,
        name=f"config/{template_name}",
        context=context,
        status_code=status_code,
    )


def _secrets_env_key(component: str, section: str, field: str) -> str:
    """Build the secrets.env key for a secret field.

    Convention: WEEWX_CLEARSKIES_<COMPONENT>_<SECTION>_<FIELD>
    """
    return f"WEEWX_CLEARSKIES_{component.upper()}_{section.upper()}_{field.upper()}"


def _section_display_name(component: str, section: str) -> str:
    return _SECTION_DISPLAY.get((component, section), f"{component}/{section}")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def config_dashboard(request: Request) -> HTMLResponse:
    """Render the config dashboard — section nav + current value overview."""
    _require_session(request)
    assert _config_dir is not None

    all_sections = get_all_sections(_config_dir)

    # Build structured nav data: list of (component, section, display_name, values)
    nav_sections = []
    for comp, sec, display_name, _secrets in _SECTION_META:
        values = all_sections.get(comp, {}).get(sec, {})
        nav_sections.append({
            "component": comp,
            "section": sec,
            "display_name": display_name,
            "values": values,
        })

    return _render(
        request,
        "dashboard.html",
        {
            "nav_sections": nav_sections,
            "config_dir": str(_config_dir),
        },
    )


# ---------------------------------------------------------------------------
# Per-section edit and save
# ---------------------------------------------------------------------------


@router.get("/column-mapping", response_class=HTMLResponse)
async def column_mapping_get(request: Request) -> HTMLResponse:
    """Render the column mapping edit form."""
    _require_session(request)
    assert _config_dir is not None

    current_mapping = get_column_mapping(_config_dir)

    return _render(
        request,
        "section.html",
        {
            "component": "api",
            "section": "column_mapping",
            "display_name": "Column Mapping",
            "is_column_mapping": True,
            "mapping": current_mapping,
            "canonical_fields": _CANONICAL_FIELDS,
            "secret_fields": (),
            "values": {},
            "result": None,
            "error": None,
        },
    )


@router.post("/column-mapping", response_class=HTMLResponse)
async def column_mapping_post(request: Request) -> HTMLResponse:
    """Save column mapping and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    # Form fields are named "col_<db_column>" for each mapping entry
    mapping: dict[str, str | None] = {}
    for key, value in form.multi_items():
        if key.startswith("col_"):
            db_col = key[4:]
            canonical = str(value).strip() or None
            mapping[db_col] = canonical

    error: str | None = None
    success = False
    try:
        update_column_mapping(mapping, _config_dir)
        success = True
    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("column_mapping_post FileNotFoundError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving column mapping: {exc}"
        logger.exception("column_mapping_post unexpected error")

    return _render(
        request,
        "result.html",
        {
            "component": "api",
            "section": "column_mapping",
            "display_name": "Column Mapping",
            "success": success,
            "error": error,
        },
        status_code=500 if error else 200,
    )


@router.get("/{component}/{section}", response_class=HTMLResponse)
async def section_get(request: Request, component: str, section: str) -> HTMLResponse:
    """Render the edit form for one config section."""
    _require_session(request)
    assert _config_dir is not None

    # Validate component/section against known-good list to prevent path traversal
    if (component, section) not in _VALID_SECTIONS:
        return _render(
            request,
            "result.html",
            {
                "component": component,
                "section": section,
                "display_name": f"{component}/{section}",
                "success": False,
                "error": f"Unknown section: {component}/{section}",
            },
            status_code=404,
        )

    values = get_section(component, section, _config_dir)
    secret_fields = _SECTION_SECRETS.get((component, section), ())

    return _render(
        request,
        "section.html",
        {
            "component": component,
            "section": section,
            "display_name": _section_display_name(component, section),
            "is_column_mapping": False,
            "values": values,
            "secret_fields": secret_fields,
            "mapping": {},
            "canonical_fields": _CANONICAL_FIELDS,
            "result": None,
            "error": None,
        },
    )


@router.post("/{component}/{section}", response_class=HTMLResponse)
async def section_post(request: Request, component: str, section: str) -> HTMLResponse:
    """Save one config section via MANAGED REGION merge, return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    # Validate component/section
    if (component, section) not in _VALID_SECTIONS:
        return _render(
            request,
            "result.html",
            {
                "component": component,
                "section": section,
                "display_name": f"{component}/{section}",
                "success": False,
                "error": f"Unknown section: {component}/{section}",
            },
            status_code=404,
        )

    form = await request.form()
    secret_fields = _SECTION_SECRETS.get((component, section), ())
    allowed_keys = _SECTION_ALLOWED_KEYS.get((component, section), frozenset())

    # Separate normal values from secret values.
    # Only accept keys in the allowed set (input validation at trust boundary).
    conf_values: dict[str, Any] = {}
    secret_values: dict[str, str] = {}

    for key, value in form.multi_items():
        if key not in allowed_keys:
            continue  # silently drop unexpected keys
        str_val = str(value).strip()
        if key in secret_fields:
            if str_val:
                secret_values[key] = str_val
        else:
            conf_values[key] = str_val

    error: str | None = None
    success = False

    try:
        conf_path = _config_dir / f"{component}.conf"
        if not conf_path.exists():
            raise FileNotFoundError(
                f"{component}.conf not found in config directory. "
                "Run the setup wizard first."
            )

        # Write secret fields into secrets.env
        for field_name, field_value in secret_values.items():
            env_key = _secrets_env_key(component, section, field_name)
            update_secrets(env_key, field_value, _config_dir)

        # ADR-027: [ui] enabled is not flippable from the UI — remove it
        # before writing so an operator cannot accidentally toggle it via the
        # config form.
        if component == "stack" and section == "ui":
            conf_values.pop("enabled", None)

        # Merge non-secret values into the managed region
        if conf_values:
            update_managed_region(conf_path, section, conf_values)

        success = True

    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("section_post FileNotFoundError: %s", exc)
    except ValueError as exc:
        error = f"Validation error: {exc}"
        logger.warning("section_post ValueError: %s", exc)
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("section_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving {component}/{section}: {exc}"
        logger.exception("section_post unexpected error")

    return _render(
        request,
        "result.html",
        {
            "component": component,
            "section": section,
            "display_name": _section_display_name(component, section),
            "success": success,
            "error": error,
        },
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# Provider connectivity test (reuses wizard.providers.test_provider)
# ---------------------------------------------------------------------------


@router.post("/test-provider", response_class=HTMLResponse)
async def config_test_provider(request: Request) -> HTMLResponse:
    """Test provider connectivity; return a result fragment."""
    _require_session(request)

    form = await request.form()
    provider_id = str(form.get("provider_id", "")).strip()
    info = get_provider(provider_id)

    if not info:
        return _render(
            request,
            "result.html",
            {
                "component": "api",
                "section": "test-provider",
                "display_name": "Provider Test",
                "success": False,
                "error": f"Unknown provider: {provider_id!r}",
                "test_result": {"success": False, "error": f"Unknown provider: {provider_id}"},
            },
            status_code=404,
        )

    credentials: dict[str, str] = {}
    for field_name in info.auth_fields:
        credentials[field_name] = str(form.get(field_name, "")).strip()

    result = test_provider(info, credentials)

    return _render(
        request,
        "result.html",
        {
            "component": "api",
            "section": "test-provider",
            "display_name": f"Provider Test — {info.display_name}",
            "success": result.get("success", False),
            "error": result.get("error"),
            "test_result": result,
            "test_provider_id": provider_id,
            "test_provider_name": info.display_name,
        },
    )

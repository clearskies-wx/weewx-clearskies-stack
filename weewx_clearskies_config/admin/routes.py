"""FastAPI router for the admin landing page, domain-organized sections, and
per-component config editing.

Provides the top-level admin UI at /admin — a domain-organized overview of
all configuration areas.  Individual sections load as HTMX fragments into
the content area.  Also handles the per-component configuration pages that
were formerly in config/routes.py.

Route summary (admin landing + domain sections):
  GET  /admin                         — landing page (requires session)
  GET  /admin/pages                   — page visibility edit form fragment
  POST /admin/pages                   — save page visibility
  GET  /admin/branding                — appearance/branding edit form
  POST /admin/branding                — save branding.json appearance fields
  GET  /admin/social                  — social links edit form
  POST /admin/social                  — save branding.json social fields
  GET  /admin/analytics               — analytics & privacy edit form
  POST /admin/analytics               — save branding.json analytics/privacy fields
  GET  /admin/earthquakes             — earthquake settings edit form
  POST /admin/earthquakes             — save stack.conf [earthquakes]
  GET  /admin/tls                     — TLS settings edit form
  POST /admin/tls                     — save stack.conf [tls]
  GET  /admin/connection              — API connection settings
  POST /admin/connection              — update API URL, caddy.env, reload Caddy
  GET  /admin/section/sky_classification — sky classification calibration form (custom template)
  POST /admin/section/sky_classification — save api.conf [sky_classification] (generic handler)
  GET  /admin/haze-calibration        — haze calibration settings + status
  POST /admin/haze-calibration        — save api.conf [conditions] haze keys
  POST /admin/haze-calibration/reset  — reset calibration data via API
  GET  /admin/geographic-features     — geographic features (PMTiles) status + update trigger
  POST /admin/geographic-features/update — trigger PMTiles download via API
  GET  /admin/now-layout              — card layout editor form
  POST /admin/now-layout              — save now-layout.json to config dir

Route summary (config editor — formerly config/routes.py):
  GET  /admin/config                          — config dashboard (all sections)
  GET  /admin/config/{component}/{section}    — section edit form fragment
  POST /admin/config/{component}/{section}    — save section, return result fragment
  GET  /admin/config/column-mapping           — column mapping form
  POST /admin/config/column-mapping           — update column mapping, return result
  POST /admin/config/test-provider            — test provider connectivity
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from weewx_clearskies_config.auth import COOKIE_NAME, SessionManager
from weewx_clearskies_config.config.reader import (
    get_all_sections,
    get_column_mapping,
    get_section,
    read_branding,
    read_pages,
)
from weewx_clearskies_config.config.updater import (
    update_column_mapping,
    update_managed_region,
    update_secrets,
)
from weewx_clearskies_config.i18n import get_current_locale, translate
from weewx_clearskies_config.wizard.providers import PROVIDERS, get_provider, test_provider

logger = logging.getLogger(__name__)


def _(key: str) -> str:
    """Translate *key* using the current request's wizard/admin UI locale.

    Python-code counterpart to the Jinja2 ``_()`` global registered in
    app.py. See the identical helper in wizard/routes.py for the full
    rationale — kept as a local copy rather than a shared import so each
    router module has no import-time dependency on the other.
    """
    return translate(key, get_current_locale())

# Haze calibration defaults
_HAZE_DEFAULTS: dict[str, str] = {
    "haze_detection": "true",
    "gamma": "0.45",
    "openaq_sensor_id": "",
}

# Forecast correction defaults
_FC_DEFAULTS: dict[str, str] = {
    "enabled": "false",
    "collection_enabled": "true",
    "retrain_schedule": "daily",
    "retrain_day": "0",
    "min_samples": "500",
    "retention_years": "3",
    "db_path": "/etc/weewx-clearskies/forecast_correction.db",
    "model_path": "/etc/weewx-clearskies/forecast_correction_model.pkl",
}

# ---------------------------------------------------------------------------
# Module-level state injected by create_admin_router()
# ---------------------------------------------------------------------------

_templates: Jinja2Templates | None = None
_session_manager: SessionManager | None = None
_config_dir: Path | None = None
_dashboard_root: Path | None = None

router = APIRouter(prefix="/admin", tags=["admin"])


def create_admin_router(
    templates: Jinja2Templates,
    session_manager: SessionManager,
    config_dir: Path,
    dashboard_root: Path,
) -> APIRouter:
    """Configure the admin router with shared app objects and return it."""
    global _templates, _session_manager, _config_dir, _dashboard_root  # noqa: PLW0603
    _templates = templates
    _session_manager = session_manager
    _config_dir = config_dir
    _dashboard_root = dashboard_root
    from weewx_clearskies_config.registry import registry
    manifest_path = dashboard_root / "card-manifest.json"
    registry.load_card_config_fields(str(manifest_path))
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

    raise StarletteHTTPException(status_code=401, detail=_("Authentication required"))


def _render(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    assert _templates is not None, "Admin router not initialised"
    return _templates.TemplateResponse(
        request=request,
        name=f"admin/{template_name}",
        context=context,
        status_code=status_code,
    )


def _render_result(
    request: Request,
    *,
    section_slug: str,
    display_name: str,
    success: bool,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return _render(
        request,
        "result.html",
        {
            "section_slug": section_slug,
            "display_name": display_name,
            "success": success,
            "error": error,
        },
        status_code=status_code,
    )


def _get_with_defaults(section_values: dict[str, str], defaults: dict[str, str]) -> dict[str, str]:
    """Return section_values merged over defaults (section_values wins)."""
    result = dict(defaults)
    result.update(section_values)
    return result


def _get_api_client():  # type: ignore[return]
    """Build an ApiClient for the known API using proxy-auth mode.

    Returns None if no known API is configured or proxy secret is missing.
    """
    if _config_dir is None:
        return None
    from weewx_clearskies_config.wizard.known_apis import load_known_apis
    from weewx_clearskies_config.wizard.state_persistence import _read_secrets_env
    known = load_known_apis(_config_dir)
    if not known:
        return None
    api_url = next(iter(known))
    secrets = _read_secrets_env(_config_dir)
    proxy_secret = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")
    if not proxy_secret:
        return None
    from weewx_clearskies_config.wizard.api_client import ApiClient
    return ApiClient(api_url, proxy_secret=proxy_secret)


def _fetch_api_providers() -> dict[str, dict[str, Any]]:
    """Fetch all provider configs from the API's /setup/current-config.

    Returns a dict keyed by domain (forecast, alerts, aqi, radar, earthquakes),
    each value a flat dict like ``{"provider": "librewxr", "librewxr_endpoint": "..."}``.
    Returns ``{}`` if the API is unreachable.
    """
    client = _get_api_client()
    if client is None:
        return {}
    try:
        config = client.get_current_config()
    except Exception:  # noqa: BLE001
        logger.warning("Could not fetch current config from API for provider sections", exc_info=True)
        return {}
    raw_providers = config.get("providers", {})
    if not isinstance(raw_providers, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for domain, pdata in raw_providers.items():
        if not isinstance(pdata, dict):
            continue
        flat: dict[str, Any] = {"provider": str(pdata.get("provider", ""))}
        for key in ("librewxr_endpoint", "librewxr_bounds", "iframe_url",
                    "aeris_forecast_model", "nws_user_agent_contact"):
            val = pdata.get(key)
            if val:
                flat[key] = str(val)
        result[domain] = flat
    return result


def _read_calibration_state() -> dict | None:
    """Fetch calibration state from the API.

    Returns the API's calibration-state response dict, or None if the
    API is unreachable or not configured.
    """
    client = _get_api_client()
    if client is None:
        return None
    try:
        response = client._request("GET", "/setup/calibration-state")
        return response.json()
    except Exception:  # noqa: BLE001
        logger.warning("Could not fetch calibration state from API", exc_info=True)
        return None


def _fetch_geographic_features_status() -> dict | None:
    """Fetch geographic features status from the API.

    Returns the API's geographic-features/status response dict, or None if
    the API is unreachable or not configured.
    """
    client = _get_api_client()
    if client is None:
        return None
    try:
        response = client._request("GET", "/api/v1/geographic-features/status")
        return response.json()
    except Exception:  # noqa: BLE001
        logger.warning("Could not fetch geographic features status from API", exc_info=True)
        return None


def _fetch_forecast_correction_status() -> dict | None:
    """Fetch forecast correction status from the API.

    Returns the API's forecast-correction/status response dict, or None if
    the API is unreachable or not configured.
    """
    client = _get_api_client()
    if client is None:
        return None
    try:
        response = client._request("GET", "/setup/forecast-correction/status")
        return response.json()
    except Exception:  # noqa: BLE001
        logger.warning("Could not fetch forecast correction status from API", exc_info=True)
        return None


def _safe_float_range(form: Any, key: str, lo: float, hi: float, defaults: dict) -> str:
    """Return a validated float string from form data within [lo, hi], or the default."""
    raw = str(form.get(key, "")).strip()
    if raw:
        try:
            val = float(raw)
            if lo <= val <= hi:
                return raw
        except ValueError:
            pass
    return defaults[key]


# ---------------------------------------------------------------------------
# Config editor helpers (formerly config/routes.py)
# ---------------------------------------------------------------------------


def _render_config(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a config/ template (used by the per-component config editor)."""
    assert _templates is not None, "Admin router not initialised"
    return _templates.TemplateResponse(
        request=request,
        name=f"config/{template_name}",
        context=context,
        status_code=status_code,
    )


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
    # stack.conf sections — webcam is a UI concern, written by the wizard to stack.conf
    ("stack", "ui", "UI Settings", ()),
    ("stack", "webcam", "Webcam", ()),
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
    ("api", "radar"):       frozenset({"provider", "librewxr_endpoint", "librewxr_bounds"}),
    ("stack", "webcam"):    frozenset({"enabled", "image_url", "video_url", "refresh_interval"}),
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

# Canonical field names available for column mapping
# Sourced from the weewx standard schema; surfaced as datalist options in the UI.
_CANONICAL_FIELDS = (
    "dateTime", "usUnits", "interval", "barometer", "pressure", "altimeter",
    "inTemp", "outTemp", "inHumidity", "outHumidity", "windSpeed", "windDir",
    "windGust", "windGustDir", "rain", "rainRate", "dewpoint", "windchill",
    "heatindex", "ET", "radiation", "UV", "extraTemp1", "extraTemp2", "extraTemp3",
    "soilTemp1", "soilTemp2", "soilTemp3", "soilTemp4", "leafTemp1", "leafTemp2",
    "extraHumid1", "extraHumid2", "soilMoist1", "soilMoist2", "soilMoist3",
    "soilMoist4", "leafWet1", "leafWet2", "rxCheckPercent", "txBatteryStatus",
    "consBatteryVoltage", "hail", "hailRate", "heatingTemp", "heatingVoltage",
    "supplyVoltage", "referenceVoltage", "windBatteryStatus", "rainBatteryStatus",
    "outTempBatteryStatus", "inTempBatteryStatus", "lightning_strike_count",
    "lightning_distance", "pm1_0", "pm2_5", "pm10_0", "co2",
)

_PROVIDER_DOMAINS = frozenset({"forecast", "alerts", "aqi", "earthquakes", "radar"})


def _secrets_env_key(component: str, section: str, field: str) -> str:
    """Build the secrets.env key for a secret field.

    Convention: WEEWX_CLEARSKIES_<COMPONENT>_<SECTION>_<FIELD>
    """
    return f"WEEWX_CLEARSKIES_{component.upper()}_{section.upper()}_{field.upper()}"


def _section_display_name(component: str, section: str) -> str:
    return _SECTION_DISPLAY.get((component, section), f"{component}/{section}")


def _get_api_provider_values(section: str) -> dict[str, Any] | None:
    """Fetch provider config for *section* from the API's /setup/current-config.

    Returns a flat dict (e.g. ``{"provider": "librewxr", "librewxr_endpoint": "..."}``),
    or None if the API is unreachable or the section has no provider configured.
    The API on the weewx host is the single authority for provider config;
    the local api.conf on weather-dev may be stale.
    """
    if _config_dir is None or section not in _PROVIDER_DOMAINS:
        return None
    try:
        from weewx_clearskies_config.wizard.known_apis import load_known_apis
        from weewx_clearskies_config.wizard.state_persistence import _read_secrets_env
        from weewx_clearskies_config.wizard.api_client import ApiClient

        known = load_known_apis(_config_dir)
        if not known:
            return None
        api_url = next(iter(known))
        secrets = _read_secrets_env(_config_dir)
        proxy_secret = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")
        if not proxy_secret:
            return None
        client = ApiClient(api_url, proxy_secret=proxy_secret)
        config = client.get_current_config()
    except Exception:  # noqa: BLE001
        logger.warning("Could not fetch provider config from API for section %s", section, exc_info=True)
        return None

    providers = config.get("providers", {})
    provider_data = providers.get(section)
    if not provider_data or not isinstance(provider_data, dict):
        return None

    values: dict[str, Any] = {"provider": str(provider_data.get("provider", ""))}
    for key in ("librewxr_endpoint", "librewxr_bounds", "iframe_url",
                "aeris_forecast_model", "nws_user_agent_contact"):
        val = provider_data.get(key)
        if val:
            values[key] = str(val)
    return values


# ---------------------------------------------------------------------------
# Config dashboard and per-section editor (formerly config/routes.py)
# ---------------------------------------------------------------------------


@router.get("/config", response_class=HTMLResponse)
@router.get("/config/", response_class=HTMLResponse)
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

    return _render_config(
        request,
        "dashboard.html",
        {
            "nav_sections": nav_sections,
            "config_dir": str(_config_dir),
        },
    )


@router.get("/config/column-mapping", response_class=HTMLResponse)
async def column_mapping_get(request: Request) -> HTMLResponse:
    """Render the column mapping edit form."""
    _require_session(request)
    assert _config_dir is not None

    current_mapping = get_column_mapping(_config_dir)

    return _render_config(
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


@router.post("/config/column-mapping", response_class=HTMLResponse)
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

    return _render_config(
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


@router.get("/config/{component}/{section}", response_class=HTMLResponse)
async def config_section_get(request: Request, component: str, section: str) -> HTMLResponse:
    """Render the edit form for one config section."""
    _require_session(request)
    assert _config_dir is not None

    # Validate component/section against known-good list to prevent path traversal
    if (component, section) not in _VALID_SECTIONS:
        return _render_config(
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

    # Provider sections read from the API (authoritative) with local fallback.
    if section in _PROVIDER_DOMAINS:
        values = _get_api_provider_values(section) or get_section(component, section, _config_dir)
    else:
        values = get_section(component, section, _config_dir)
    secret_fields = _SECTION_SECRETS.get((component, section), ())

    # Build provider metadata from the single source of truth (wizard/providers.py).
    provider_meta: dict[str, dict] = {
        p.provider_id: {
            "display": p.display_name,
            "coverage": p.geographic_coverage,
            "keyless": len(p.auth_fields) == 0,
            "fields": list(p.auth_fields),
            "notes": p.notes,
            "signup_url": p.signup_url,
        }
        for p in PROVIDERS
    }
    domain_providers: dict[str, list[str]] = {}
    for p in PROVIDERS:
        domain_providers.setdefault(p.domain, []).append(p.provider_id)

    return _render_config(
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
            "provider_meta": provider_meta,
            "domain_providers": domain_providers,
            "result": None,
            "error": None,
        },
    )


@router.post("/config/{component}/{section}", response_class=HTMLResponse)
async def config_section_post(request: Request, component: str, section: str) -> HTMLResponse:
    """Save one config section via MANAGED REGION merge, return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    # Validate component/section
    if (component, section) not in _VALID_SECTIONS:
        return _render_config(
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

    # LibreWxR endpoint mode radio → resolve to actual endpoint URL.
    if section == "radar":
        endpoint_mode = str(form.get("librewxr_endpoint_mode", "")).strip()
        if endpoint_mode == "selfhosted":
            url_val = conf_values.get("librewxr_endpoint", "")
            if not url_val:
                conf_values["librewxr_endpoint"] = "https://api.librewxr.net"
        else:
            conf_values["librewxr_endpoint"] = "https://api.librewxr.net"

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
        logger.warning("config_section_post FileNotFoundError: %s", exc)
    except ValueError as exc:
        error = f"Validation error: {exc}"
        logger.warning("config_section_post ValueError: %s", exc)
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("config_section_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving {component}/{section}: {exc}"
        logger.exception("config_section_post unexpected error")

    return _render_config(
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


@router.post("/config/test-provider", response_class=HTMLResponse)
async def config_test_provider(request: Request) -> HTMLResponse:
    """Test provider connectivity; return a result fragment."""
    _require_session(request)

    form = await request.form()
    provider_id = str(form.get("provider_id", "")).strip()
    info = get_provider(provider_id)

    if not info:
        return _render_config(
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

    return _render_config(
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


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


# Human-readable labels for registry domain groups shown on the landing page.
_GROUP_LABELS: dict[str, str] = {
    "station": "Station",
    "providers": "Providers",
    "appearance": "Appearance",
    "dashboard": "Dashboard",
    "advanced": "Advanced",
    "cards": "Card Settings",
}

# Custom sections that exist as dedicated routes but are not in the registry.
# Each entry carries the fields shown as a card on the landing overview.
# "url" is the HTMX GET target; "description" is a one-line summary shown
# instead of a dl when there are no landing_display fields to render.
_CUSTOM_SECTIONS: list[dict] = [
    {
        "section_id": "station-identity",
        "display_name": "Station Identity",
        "group": "station",
        "url": "/admin/config/stack/ui",
        "description": "",
    },
    {
        "section_id": "database",
        "display_name": "Database",
        "group": "station",
        "url": "/admin/config/api/database",
        "description": "",
    },
    {
        "section_id": "connection",
        "display_name": "API Connection",
        "group": "station",
        "url": "/admin/connection",
        "description": "",
    },
    {
        "section_id": "forecast-provider",
        "display_name": "Forecast",
        "group": "providers",
        "url": "/admin/config/api/forecast",
        "description": "",
    },
    {
        "section_id": "alerts-provider",
        "display_name": "Alerts",
        "group": "providers",
        "url": "/admin/config/api/alerts",
        "description": "",
    },
    {
        "section_id": "aqi-provider",
        "display_name": "AQI",
        "group": "providers",
        "url": "/admin/config/api/aqi",
        "description": "",
    },
    {
        "section_id": "earthquakes-provider",
        "display_name": "Earthquakes Provider",
        "group": "providers",
        "url": "/admin/config/api/earthquakes",
        "description": "",
    },
    {
        "section_id": "radar-provider",
        "display_name": "Radar",
        "group": "providers",
        "url": "/admin/config/api/radar",
        "description": "",
    },
    {
        "section_id": "now-layout",
        "display_name": "Now Page Layout",
        "group": "dashboard",
        "url": "/admin/now-layout",
        "description": "Drag-and-drop card arrangement for the Now page.",
    },
    {
        "section_id": "column-mapping",
        "display_name": "Column Mapping",
        "group": "dashboard",
        "url": "/admin/config/column-mapping",
        "description": "Map database columns to weewx canonical field names.",
    },
    {
        "section_id": "haze-calibration",
        "display_name": "Haze Calibration",
        "group": "advanced",
        "url": "/admin/haze-calibration",
        "description": "",
    },
    {
        "section_id": "geographic-features",
        "display_name": "Geographic Features",
        "group": "advanced",
        "url": "/admin/geographic-features",
        "description": "OpenStreetMap boundaries, roads, and water for the satellite map overlay.",
    },
    {
        "section_id": "forecast-correction",
        "display_name": "Forecast Correction",
        "group": "advanced",
        "url": "/admin/forecast-correction",
        "description": "Temperature bias correction using forecast-observation pairs and Random Forest regression.",
    },
]


@router.get("", response_class=HTMLResponse, response_model=None)
@router.get("/", response_class=HTMLResponse, response_model=None)
async def admin_landing(request: Request) -> HTMLResponse | RedirectResponse:
    """Render the admin landing page — registry-driven domain-organized overview."""
    _require_session(request)
    assert _config_dir is not None

    api_conf = _config_dir / "api.conf"
    if not api_conf.exists():
        return RedirectResponse("/wizard", status_code=303)

    from weewx_clearskies_config.registry import registry

    # Build ordered domain group list: priority groups first (station, providers
    # are custom-only — not in the registry), then registry groups, then any
    # remaining custom-only groups.
    registry_groups = list(registry.get_all_domain_groups())
    all_group_names = []
    seen: set[str] = set()
    # Prepend custom-only groups that come before any registry group (station, providers)
    _priority_groups = ["station", "providers"]
    for g in _priority_groups:
        if g not in seen:
            all_group_names.append(g)
            seen.add(g)
    for g in registry_groups:
        if g not in seen:
            all_group_names.append(g)
            seen.add(g)
    # Any remaining custom-only groups not yet added
    for cs in _CUSTOM_SECTIONS:
        g = cs["group"]
        if g not in seen:
            all_group_names.append(g)
            seen.add(g)

    domain_groups = [(g, _GROUP_LABELS.get(g, g.title())) for g in all_group_names]

    # Build sections_by_group: registry sections first, then custom sections, per group
    sections_by_group: dict[str, list] = {g: [] for g in all_group_names}
    for g in all_group_names:
        for section in registry.get_sections_for_group(g):
            sections_by_group[g].append({"type": "registry", "section": section})
    for cs in _CUSTOM_SECTIONS:
        g = cs["group"]
        if g in sections_by_group:
            sections_by_group[g].append({"type": "custom", "section": cs})

    # Collect landing display field values for registry sections that have
    # fields with admin_landing_display=True.
    landing_values: dict[str, list[tuple[str, Any]]] = {}
    for g in all_group_names:
        for entry in sections_by_group[g]:
            if entry["type"] != "registry":
                continue
            section = entry["section"]
            fields = registry.get_fields_for_section(section.section_id)
            display_fields = [f for f in fields if f.admin_landing_display]
            if display_fields:
                values = _read_section_values(section, fields)
                landing_values[section.section_id] = [
                    (f.label, values.get(f.config_key, f.default))
                    for f in display_fields
                ]

    # Collect custom-section landing values: provider "provider" keys, connection URL,
    # station identity highlights, haze calibration summary.
    api_providers = _fetch_api_providers()
    from weewx_clearskies_config.wizard.known_apis import load_known_apis
    known = load_known_apis(_config_dir)
    connection_url = next(iter(known), "")
    api_section = get_section("api", "api", _config_dir)
    connection_bind = (
        f"{api_section.get('bind_host', '')}:{api_section.get('bind_port', '8765')}"
        if api_section.get("bind_host") else ""
    )
    ui_values = get_section("stack", "ui", _config_dir)
    db_values = get_section("api", "database", _config_dir)
    haze_values = _get_with_defaults(get_section("api", "conditions", _config_dir), _HAZE_DEFAULTS)
    haze_calibration = _read_calibration_state()

    _provider_domains = {
        "forecast-provider": "forecast",
        "alerts-provider": "alerts",
        "aqi-provider": "aqi",
        "earthquakes-provider": "earthquakes",
        "radar-provider": "radar",
    }
    custom_landing_values: dict[str, list[tuple[str, Any]]] = {}

    if ui_values:
        rows: list[tuple[str, Any]] = []
        if ui_values.get("station_name"):
            rows.append(("Name", ui_values["station_name"]))
        if ui_values.get("timezone"):
            rows.append(("Timezone", ui_values["timezone"]))
        if ui_values.get("latitude") and ui_values.get("longitude"):
            rows.append(("Coordinates", f"{ui_values['latitude']}, {ui_values['longitude']}"))
        if rows:
            custom_landing_values["station-identity"] = rows

    if db_values:
        rows = []
        if db_values.get("host"):
            port_str = f":{db_values['port']}" if db_values.get("port") else ""
            rows.append(("Host", f"{db_values['host']}{port_str}"))
        if db_values.get("name"):
            rows.append(("Database", db_values["name"]))
        if db_values.get("user"):
            rows.append(("User", db_values["user"]))
        if rows:
            custom_landing_values["database"] = rows

    if connection_url:
        rows = [("API URL", connection_url)]
        if connection_bind:
            rows.append(("Bind", connection_bind))
        custom_landing_values["connection"] = rows

    for cs_id, domain in _provider_domains.items():
        pdata = api_providers.get(domain) or get_section("api", domain, _config_dir)
        provider_val = pdata.get("provider", "") if pdata else ""
        custom_landing_values[cs_id] = [("Provider", provider_val or "not set")]

    # Haze calibration summary
    haze_rows: list[tuple[str, Any]] = [("Detection", haze_values.get("haze_detection", "true"))]
    if haze_calibration is None:
        haze_rows.append(("Status", "API unreachable"))
    else:
        haze_rows.append(("Status",
            haze_calibration.get("overall_state", "no-data").replace("-", " ").capitalize()))
        haze_rows.append(("Months calibrated", f"{haze_calibration.get('months_calibrated', 0)} / 12"))
        if haze_calibration.get("openaq_sensor"):
            s = haze_calibration["openaq_sensor"]
            haze_rows.append(("Sensor", f"{s['name']} ({s['distance_km']:.1f} km)"))
    custom_landing_values["haze-calibration"] = haze_rows

    # Geographic features summary
    geo_status = _fetch_geographic_features_status()
    geo_rows: list[tuple[str, Any]] = []
    if geo_status is None:
        geo_rows.append(("Status", "API unreachable"))
    elif geo_status.get("available"):
        size_bytes = geo_status.get("size_bytes")
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes else "unknown size"
        geo_rows.append(("Status", f"Available ({size_str})"))
        updated_at = geo_status.get("updated_at")
        if updated_at:
            geo_rows.append(("Updated", updated_at[:10] if len(updated_at) >= 10 else updated_at))
    else:
        geo_rows.append(("Status", "Not downloaded"))
    custom_landing_values["geographic-features"] = geo_rows

    return _render(
        request,
        "landing.html",
        {
            "domain_groups": domain_groups,
            "sections_by_group": sections_by_group,
            "landing_values": landing_values,
            "custom_landing_values": custom_landing_values,
        },
    )


# ---------------------------------------------------------------------------
# T2.1 — Generic registry section handler
# ---------------------------------------------------------------------------


def _find_section(section_id: str):  # type: ignore[return]
    """Look up a section in the registry by section_id.

    Raises HTTPException 404 if not found.
    """
    from fastapi import HTTPException
    from weewx_clearskies_config.registry import registry

    for group in registry.get_all_domain_groups():
        for s in registry.get_sections_for_group(group):
            if s.section_id == section_id:
                return s
    raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")


def _read_section_values(section, fields) -> dict:  # type: ignore[return]
    """Read current field values for *section* from the appropriate backend.

    Returns a dict keyed by config_key (matching the field declarations).
    For .conf-based sources, get_section() returns keys that should already
    match the config_key names.  For JSON sources (branding.json, pages.json)
    the mapping is handled here.
    """
    assert _config_dir is not None
    source = section.config_source

    if source == "stack.conf":
        return get_section("stack", section.section_id, _config_dir)

    elif source == "api.conf":
        return get_section("api", section.section_id, _config_dir)

    elif source == "branding.json":
        branding = read_branding(_config_dir)
        # Build result keyed by config_key for each field
        values: dict = {}
        for field in fields:
            key = field.config_key
            # config_target may be "branding.json" (top-level) or
            # "branding.json:<sub_key>" (nested dict)
            target = field.config_target
            if ":" in target:
                sub = target.split(":", 1)[1]
                nested = branding.get(sub, {})
                values[key] = nested.get(key, field.default)
            else:
                values[key] = branding.get(key, field.default)
        return values

    elif source == "pages.json":
        pages_data = read_pages(_config_dir)
        hidden: list = pages_data.get("hidden", [])
        # The pages section has one field: hidden_pages (checkbox_group)
        # The value is the list of hidden slugs
        return {"hidden_pages": hidden}

    else:
        logger.warning(
            "_read_section_values: unknown config_source %r for section %s",
            source,
            section.section_id,
        )
        return {}


@router.get("/section/{section_id}", response_class=HTMLResponse)
async def generic_section_get(request: Request, section_id: str) -> HTMLResponse:
    """Render a registry-defined section edit form."""
    _require_session(request)
    assert _config_dir is not None

    from weewx_clearskies_config.registry import registry

    section = _find_section(section_id)
    fields = registry.get_fields_for_section(section_id)
    values = _read_section_values(section, fields)

    template_name = section.custom_template if section.custom_template else "generic_section.html"
    return _render(request, template_name, {
        "section": section,
        "fields": fields,
        "values": values,
    })


@router.post("/section/{section_id}", response_class=HTMLResponse)
async def generic_section_post(request: Request, section_id: str) -> HTMLResponse:
    """Save a registry-defined section and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    from weewx_clearskies_config.registry import registry
    from weewx_clearskies_config.registry.validation import (
        validate_form_against_fields,
        extract_field_values,
        save_field_values,
    )

    section = _find_section(section_id)
    fields = registry.get_fields_for_section(section_id)

    form = await request.form()
    # Collect multi-value fields (e.g. checkbox_group) as lists
    form_data: dict = {}
    for field in fields:
        raw = form.getlist(field.config_key)
        if len(raw) > 1:
            form_data[field.config_key] = raw
        elif len(raw) == 1:
            form_data[field.config_key] = raw[0]
        # absent keys stay absent (boolean fields → False, etc.)

    errors = validate_form_against_fields(form_data, fields)
    if errors:
        values = _read_section_values(section, fields)
        return _render(request, "generic_section.html", {
            "section": section,
            "fields": fields,
            "values": values,
            "error": "; ".join(errors),
        }, status_code=422)

    values = extract_field_values(form_data, fields)

    error: str | None = None
    success = False
    try:
        save_field_values(values, section, str(_config_dir))
        success = True
    except Exception as exc:  # noqa: BLE001
        error = _("Error saving: {detail}").format(detail=exc)
        logger.exception("generic_section_post error for %s", section_id)

    return _render_result(
        request,
        section_slug=section_id,
        display_name=section.display_name,
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# API Connection
# ---------------------------------------------------------------------------


@router.get("/connection", response_class=HTMLResponse)
async def connection_get(request: Request) -> HTMLResponse:
    """Render the API connection settings form."""
    _require_session(request)
    assert _config_dir is not None

    from weewx_clearskies_config.wizard.known_apis import load_known_apis

    known = load_known_apis(_config_dir)
    api_url = next(iter(known), "")
    api_values = get_section("api", "api", _config_dir)
    bind_host = api_values.get("bind_host", "")
    bind_port = api_values.get("bind_port", "8765")

    return _render(
        request,
        "connection.html",
        {
            "api_url": api_url,
            "bind_host": bind_host,
            "bind_port": bind_port,
        },
    )


@router.post("/connection", response_class=HTMLResponse)
async def connection_post(request: Request) -> HTMLResponse:
    """Save API connection settings, update caddy.env, and reload Caddy."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()
    api_url = str(form.get("api_url", "")).strip()

    error: str | None = None
    success = False

    if not api_url:
        error = _("API URL is required.")
    elif not api_url.startswith("https://"):
        error = _("API URL must start with https://")

    if not error:
        try:
            from weewx_clearskies_config.wizard.known_apis import (
                load_known_apis,
                save_known_api,
            )
            from weewx_clearskies_config.wizard.config_writer import write_caddy_env
            from weewx_clearskies_config.wizard.state import WizardState

            known = load_known_apis(_config_dir)
            old_url = next(iter(known), None)
            old_fp = known.get(old_url, "") if old_url else ""

            if old_url and old_url != api_url:
                # Remove old entry, re-pin under new URL with same fingerprint.
                # Operator can re-run wizard if cert changed too.
                known_path = _config_dir / "known_apis.json"
                import json as _json

                new_known = {api_url: old_fp}
                known_path.write_text(_json.dumps(new_known, indent=2), encoding="utf-8")
                logger.info("Updated known_apis.json: %s -> %s", old_url, api_url)
            elif not old_url:
                save_known_api(_config_dir, api_url, "")

            # Write caddy.env
            stub_state = WizardState(api_address=api_url)
            write_caddy_env(stub_state, _config_dir)

            # Reload Caddy
            import subprocess

            subprocess.run(
                ["sudo", "systemctl", "reload", "caddy"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            logger.info("connection_post: Caddy reloaded after API URL change to %s", api_url)
            success = True
        except OSError as exc:
            error = _("File write error: {detail}").format(detail=exc)
            logger.error("connection_post OSError: %s", exc)
        except subprocess.CalledProcessError as exc:
            error = _("Caddy reload failed: {detail}").format(
                detail=exc.stderr.decode() if exc.stderr else exc
            )
            logger.error("connection_post Caddy reload failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            error = _("Unexpected error: {detail}").format(detail=exc)
            logger.exception("connection_post unexpected error")

    return _render_result(
        request,
        section_slug="connection",
        display_name=_("API Connection"),
        success=success,
        error=error,
        status_code=500 if error else 200,
    )



# ---------------------------------------------------------------------------
# T8.2b — Haze calibration
# ---------------------------------------------------------------------------


@router.get("/openaq-sensors-fragment", response_class=HTMLResponse)
async def openaq_sensors_fragment(request: Request) -> HTMLResponse:
    """Return HTMX fragment with a select of nearby reference sensors.

    The returned HTML is a ``<select>`` that, when the user picks an option,
    copies the sensor ID into the manual-entry ``<input id="manual_sensor_id">``
    on the same page.  No separate form submission — one submission path only.
    """
    _require_session(request)
    client = _get_api_client()
    sensors: list[dict] = []
    error: str | None = None

    if client is None:
        error = _("Cannot connect to API.")
    else:
        try:
            response = client._request("GET", "/setup/openaq-sensors")
            data = response.json()
            sensors = data.get("sensors", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("openaq_sensors_fragment: could not load sensors: %s", exc)
            error = _("Could not load sensors: {detail}").format(detail=exc)

    if error:
        escaped = error.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return HTMLResponse(
            f'<p style="font-size:0.875rem;color:var(--pico-del-color)">{escaped}</p>'
        )
    if not sensors:
        return HTMLResponse(
            '<p style="font-size:0.875rem;color:var(--pico-muted-color)">'
            + _("No reference sensors found within 25 km.")
            + "</p>"
        )

    def _esc(v: object) -> str:
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    options = [f'<option value="">{_esc(_("— Select a sensor —"))}</option>']
    for s in sensors:
        sensor_id = _esc(s.get("sensor_id", ""))
        label = _esc(
            f"{s.get('name', '?')} ({float(s.get('distance_km', 0)):.1f} km, ID: {s.get('sensor_id', '?')})"
        )
        options.append(f'<option value="{sensor_id}">{label}</option>')

    select_html = (
        f'<label for="sensor-select" style="font-size:0.875rem">{_esc(_("Reference sensors nearby"))}</label>'
        f'<select id="sensor-select" aria-label="{_esc(_("Select a reference sensor"))}"'
        ' onchange="document.getElementById(\'manual_sensor_id\').value = this.value">'
        + "".join(options)
        + "</select>"
        f'<small style="display:block;margin-block:0.25rem">{_esc(_("Select a sensor to populate the ID field below, then click “Set sensor override.” Only reference-grade (AQMD/regulatory) monitors are listed."))}</small>'
    )
    return HTMLResponse(select_html)


@router.get("/haze-calibration", response_class=HTMLResponse)
async def haze_calibration_get(request: Request) -> HTMLResponse:
    """Render the haze calibration settings and status form."""
    _require_session(request)
    assert _config_dir is not None
    values = _get_with_defaults(
        get_section("api", "conditions", _config_dir), _HAZE_DEFAULTS
    )
    cal_state = _read_calibration_state()
    return _render(request, "haze_calibration.html", {
        "values": values,
        "defaults": _HAZE_DEFAULTS,
        "calibration": cal_state,
    })


@router.post("/haze-calibration", response_class=HTMLResponse)
async def haze_calibration_post(request: Request) -> HTMLResponse:
    """Save haze calibration settings and return result fragment."""
    _require_session(request)
    assert _config_dir is not None
    form = await request.form()
    values = {
        "haze_detection": "true" if form.get("haze_detection") else "false",
        "gamma": _safe_float_range(form, "gamma", 0.1, 1.0, _HAZE_DEFAULTS),
    }
    # openaq_sensor_id: only update when present in form (may be empty string to clear)
    if "openaq_sensor_id" in form:
        raw_sensor_id = str(form["openaq_sensor_id"]).strip()
        # Accept empty (clear) or positive integer only
        if raw_sensor_id == "" or (raw_sensor_id.isdigit() and int(raw_sensor_id) > 0):
            values["openaq_sensor_id"] = raw_sensor_id
        # else: ignore invalid value, don't persist it
    api_conf = _config_dir / "api.conf"
    error: str | None = None
    success = False
    try:
        if not api_conf.exists():
            raise FileNotFoundError("api.conf not found — run the setup wizard first.")
        update_managed_region(api_conf, "conditions", values)
        success = True
    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("haze_calibration_post FileNotFoundError: %s", exc)
    except OSError as exc:
        error = _("File write error: {detail}").format(detail=exc)
        logger.error("haze_calibration_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = _("Unexpected error: {detail}").format(detail=exc)
        logger.exception("haze_calibration_post unexpected error")
    return _render_result(request, section_slug="haze-calibration",
        display_name=_("Haze Calibration"), success=success, error=error,
        status_code=500 if error else 200)


@router.post("/haze-calibration/reset", response_class=HTMLResponse)
async def haze_calibration_reset(request: Request) -> HTMLResponse:
    """Reset calibration data via the API and return result fragment."""
    _require_session(request)
    client = _get_api_client()
    error: str | None = None
    success = False
    if client is None:
        error = _("Cannot connect to API — check that the API is running and configured.")
    else:
        try:
            response = client._request("POST", "/setup/calibration-reset")
            data = response.json()
            success = data.get("success", False)
            if not success:
                error = data.get("message", _("Reset failed — unknown error."))
        except Exception as exc:  # noqa: BLE001
            error = _("API error: {detail}").format(detail=exc)
            logger.warning("calibration_reset API error: %s", exc)
    return _render_result(request, section_slug="haze-calibration",
        display_name=_("Haze Calibration"), success=success, error=error,
        status_code=500 if error else 200)


# ---------------------------------------------------------------------------
# Phase 4 T4.1 — Geographic features (PMTiles) admin
# ---------------------------------------------------------------------------


@router.get("/geographic-features", response_class=HTMLResponse)
async def geographic_features_get(request: Request) -> HTMLResponse:
    """Render the geographic features status page."""
    _require_session(request)
    geo_status = _fetch_geographic_features_status()
    error: str | None = None
    if geo_status is None:
        error = _("Cannot connect to the API — check that the API is running and configured.")
    return _render(request, "geographic_features.html", {
        "status": geo_status,
        "error": error,
    })


@router.post("/geographic-features/update", response_class=HTMLResponse)
async def geographic_features_update(request: Request) -> HTMLResponse:
    """Trigger a PMTiles geographic features download via the API."""
    _require_session(request)
    client = _get_api_client()
    error: str | None = None
    success = False
    if client is None:
        error = _("Cannot connect to the API — check that the API is running and configured.")
    else:
        try:
            response = client._request("POST", "/setup/geographic-features/update")
            data = response.json()
            success = data.get("success", True)  # treat any 2xx as success
            if not success:
                error = data.get("message") or data.get("error") or _("Update failed — unknown error.")
        except Exception as exc:  # noqa: BLE001
            error = _("API error: {detail}").format(detail=exc)
            logger.warning("geographic_features_update API error: %s", exc)
    if success:
        return _render(request, "geographic_features.html", {
            "status": _fetch_geographic_features_status(),
            "error": None,
            "flash": _("Geographic features data updated successfully."),
        })
    return _render(request, "geographic_features.html", {
        "status": _fetch_geographic_features_status(),
        "error": error,
    }, status_code=500 if error else 200)


# ---------------------------------------------------------------------------
# Phase 7 — Forecast correction admin
# ---------------------------------------------------------------------------


@router.get("/forecast-correction", response_class=HTMLResponse)
async def forecast_correction_get(request: Request) -> HTMLResponse:
    """Render the forecast correction status, metrics, and controls page."""
    _require_session(request)
    assert _config_dir is not None
    values = _get_with_defaults(
        get_section("api", "forecast_correction", _config_dir), _FC_DEFAULTS
    )
    status = _fetch_forecast_correction_status()
    # Format epoch timestamps in station-local time for the template.
    fmt_start = fmt_end = None
    if status:
        from datetime import datetime, timezone as _tz  # noqa: PLC0415
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        # The API's current-config or station endpoint provides the timezone;
        # fall back to reading it from the correction status response or api.conf.
        station_tz_name = None
        client = _get_api_client()
        if client is not None:
            try:
                resp = client._request("GET", "/api/v1/station")
                station_tz_name = resp.json().get("data", {}).get("timezone")
            except Exception:  # noqa: BLE001
                pass
        try:
            tz = ZoneInfo(station_tz_name) if station_tz_name else _tz.utc
        except (KeyError, ValueError):
            tz = _tz.utc
        for key, target in [("date_range_start", "start"), ("date_range_end", "end")]:
            epoch = status.get(key)
            if epoch is not None:
                try:
                    dt = datetime.fromtimestamp(int(epoch), tz=_tz.utc).astimezone(tz)
                    formatted = dt.strftime("%Y-%m-%d %H:%M %Z")
                    if target == "start":
                        fmt_start = formatted
                    else:
                        fmt_end = formatted
                except (ValueError, OSError, OverflowError):
                    pass
    return _render(request, "forecast_correction.html", {
        "values": values,
        "defaults": _FC_DEFAULTS,
        "status": status,
        "fmt_date_start": fmt_start,
        "fmt_date_end": fmt_end,
    })


@router.post("/forecast-correction/toggle", response_class=HTMLResponse)
async def forecast_correction_toggle(request: Request) -> HTMLResponse:
    """Toggle forecast correction and/or pair collection via the API."""
    _require_session(request)
    client = _get_api_client()
    error: str | None = None
    success = False
    if client is None:
        error = _("Cannot connect to API — check that the API is running and configured.")
    else:
        form = await request.form()
        body = {
            "enabled": "enabled" in form,
            "collection_enabled": "collection_enabled" in form,
        }
        try:
            client._request("POST", "/setup/forecast-correction/toggle", json=body)
            success = True
        except Exception as exc:  # noqa: BLE001
            error = _("API error: {detail}").format(detail=exc)
            logger.warning("forecast_correction_toggle API error: %s", exc)
    return _render_result(
        request,
        section_slug="forecast-correction",
        display_name=_("Forecast Correction"),
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


@router.post("/forecast-correction/retrain", response_class=HTMLResponse)
async def forecast_correction_retrain(request: Request) -> HTMLResponse:
    """Trigger a model retrain via the API."""
    _require_session(request)
    client = _get_api_client()
    error: str | None = None
    success = False
    if client is None:
        error = _("Cannot connect to API — check that the API is running and configured.")
    else:
        try:
            response = client._request("POST", "/setup/forecast-correction/retrain")
            data = response.json()
            success = data.get("success", False)
            if not success:
                error = data.get("message", _("Training did not complete."))
        except Exception as exc:  # noqa: BLE001
            error = _("API error: {detail}").format(detail=exc)
            logger.warning("forecast_correction_retrain API error: %s", exc)
    return _render_result(
        request,
        section_slug="forecast-correction",
        display_name=_("Forecast Correction"),
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T4.2 — Card layout editor helpers
# ---------------------------------------------------------------------------


def _read_card_manifest() -> list[dict]:
    """Read card-manifest.json from the dashboard web root."""
    if _dashboard_root is None:
        return []
    manifest_path = _dashboard_root / "card-manifest.json"
    if not manifest_path.exists():
        return []
    try:
        with open(manifest_path) as f:
            data = json.load(f)
        return data.get("cards", [])
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read card-manifest.json from %s", manifest_path)
        return []


def _read_now_layout() -> dict:
    """Read now-layout.json from config dir, or return default empty layout."""
    if _config_dir is None:
        return {"version": 1, "cards": []}
    layout_path = _config_dir / "now-layout.json"
    if not layout_path.exists():
        return {"version": 1, "cards": []}
    try:
        with open(layout_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read now-layout.json from %s", layout_path)
        return {"version": 1, "cards": []}


# ---------------------------------------------------------------------------
# T4.2 — Card layout editor routes
# ---------------------------------------------------------------------------


@router.get("/now-layout", response_class=HTMLResponse)
async def now_layout_get(request: Request) -> HTMLResponse:
    """Render the Now Page card layout editor."""
    _require_session(request)

    manifest_cards = _read_card_manifest()
    current_layout = _read_now_layout()

    # Build active card list (in layout order) with manifest metadata
    active_types = [c["type"] for c in current_layout.get("cards", [])]
    manifest_by_type = {c["type"]: c for c in manifest_cards}

    active_cards = []
    for entry in current_layout.get("cards", []):
        meta = manifest_by_type.get(entry["type"])
        if meta:
            allowed = meta.get("allowedLayouts", [])
            default_footprint = allowed[0]["footprint"] if allowed else "tile"
            default_row_span = allowed[0]["rowSpan"] if allowed else 1
            active_cards.append({
                **meta,
                "currentFootprint": entry.get("footprint", default_footprint),
                "currentRowSpan": entry.get("rowSpan", default_row_span),
            })

    # Palette = manifest cards NOT in active layout
    palette_cards = [c for c in manifest_cards if c["type"] not in active_types]

    return _render(request, "card_layout.html", {
        "active_cards": active_cards,
        "palette_cards": palette_cards,
    })


@router.post("/now-layout", response_class=HTMLResponse)
async def now_layout_post(request: Request) -> HTMLResponse:
    """Save the card layout to now-layout.json in the config directory."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()
    layout_json_str = str(form.get("layout_json", "{}"))

    try:
        layout_data = json.loads(layout_json_str)
    except json.JSONDecodeError:
        return _render_result(
            request,
            section_slug="now-layout",
            display_name=_("Now Page Layout"),
            success=False,
            error=_("Invalid layout data"),
            status_code=422,
        )

    # Validate card types and layouts against manifest
    manifest_cards = _read_card_manifest()
    valid_types = {c["type"] for c in manifest_cards}
    _VALID_FOOTPRINTS = {"tile", "wide", "panel", "full"}
    _VALID_ROWSPANS = {1, 2, 2.5}

    cards = []
    for entry in layout_data.get("cards", []):
        card_type = entry.get("type", "")
        if card_type not in valid_types:
            logger.warning("now_layout_post: skipping unknown card type %r", card_type)
            continue
        footprint = entry.get("footprint", "tile")
        if footprint not in _VALID_FOOTPRINTS:
            footprint = "tile"
        row_span = entry.get("rowSpan", 1)
        if row_span not in _VALID_ROWSPANS:
            row_span = 1
        cards.append({
            "type": card_type,
            "footprint": footprint,
            "rowSpan": row_span,
        })

    config = {"version": 1, "cards": cards}
    layout_path = _config_dir / "now-layout.json"

    error: str | None = None
    success = False
    try:
        with open(layout_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        success = True
    except OSError as exc:
        error = _("File write error: {detail}").format(detail=exc)
        logger.error("now_layout_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = _("Unexpected error saving card layout: {detail}").format(detail=exc)
        logger.exception("now_layout_post unexpected error")

    return _render_result(
        request,
        section_slug="now-layout",
        display_name=_("Now Page Layout"),
        success=success,
        error=error,
        status_code=500 if error else 200,
    )

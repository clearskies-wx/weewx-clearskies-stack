"""FastAPI router for the admin landing page and domain-organized sections.

Provides the top-level admin UI at /admin — a domain-organized overview of
all configuration areas.  Individual sections load as HTMX fragments into
the content area.

Route summary:
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
  GET  /admin/sky-classification      — sky classification calibration form
  POST /admin/sky-classification      — save api.conf [sky_classification]
  GET  /admin/haze-calibration        — haze calibration settings + status
  POST /admin/haze-calibration        — save api.conf [conditions] haze keys
  POST /admin/haze-calibration/reset  — reset calibration data via API
  GET  /admin/now-layout              — card layout editor form
  POST /admin/now-layout              — save now-layout.json to config dir
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
    get_section,
    read_branding,
    read_pages,
)
from weewx_clearskies_config.config.updater import (
    update_branding,
    update_managed_region,
    update_pages,
)

logger = logging.getLogger(__name__)

# The 9 built-in pages.  "now" is always visible and cannot be hidden.
_ALL_PAGES = [
    {"slug": "now", "name": "Now"},
    {"slug": "forecast", "name": "Forecast"},
    {"slug": "charts", "name": "Charts"},
    {"slug": "almanac", "name": "Almanac"},
    {"slug": "earthquakes", "name": "Earthquakes"},
    {"slug": "records", "name": "Records"},
    {"slug": "reports", "name": "Reports"},
    {"slug": "about", "name": "About"},
    {"slug": "legal", "name": "Legal"},
]

# Accent colour options (matches branding.json values used by the dashboard)
_ACCENT_OPTIONS = ["blue", "teal", "indigo", "purple", "green", "amber"]

# Theme mode options
_THEME_OPTIONS = ["auto-os", "auto-sunrise", "light", "dark"]

# Kasten-Czeplak reference table for sky classification display
_KC_REFERENCE = [
    {"km_range": "0.97 – 1.00", "okta": "0 (clear)", "nws": "SKC / CLR"},
    {"km_range": "0.85 – 0.96", "okta": "1–2 (few)", "nws": "FEW"},
    {"km_range": "0.52 – 0.84", "okta": "3–4 (scattered)", "nws": "SCT"},
    {"km_range": "0.15 – 0.51", "okta": "5–7 (broken)", "nws": "BKN"},
    {"km_range": "0.00 – 0.14", "okta": "8 (overcast)", "nws": "OVC"},
]

# Sky classification defaults
_SKY_DEFAULTS = {
    "scatter_few_max": "0.97",
    "scatter_sct_max": "0.85",
    "scatter_bkn_max": "0.52",
    "overcast_km_threshold": "0.15",
    "overcast_kv_threshold": "0.03",
    "sza_min_elevation": "5.0",
}

# Haze calibration defaults
_HAZE_DEFAULTS: dict[str, str] = {
    "haze_detection": "true",
    "gamma": "0.45",
    "openaq_sensor_id": "",
}

# Earthquake section defaults
_EARTHQUAKE_DEFAULTS = {
    "radius_km": "500",
    "min_magnitude": "2.5",
    "default_days": "30",
}

# TLS mode options
_TLS_MODES = [
    {"value": "self-signed", "label": "Self-signed (development)"},
    {"value": "acme_http01", "label": "ACME HTTP-01 (Let's Encrypt, HTTP)"},
    {"value": "acme_dns01", "label": "ACME DNS-01 (Let's Encrypt, DNS)"},
    {"value": "manual", "label": "Manual (supply cert + key paths)"},
]

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


def _safe_int_range(form: Any, key: str, lo: int, hi: int, defaults: dict) -> str:
    """Return a validated int string from form data within [lo, hi], or the default."""
    raw = str(form.get(key, "")).strip()
    if raw:
        try:
            val = int(raw)
            if lo <= val <= hi:
                return str(val)
        except ValueError:
            pass
    return defaults[key]


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse, response_model=None)
@router.get("/", response_class=HTMLResponse, response_model=None)
async def admin_landing(request: Request) -> HTMLResponse | RedirectResponse:
    """Render the admin landing page — domain-organized section overview."""
    _require_session(request)
    assert _config_dir is not None

    api_conf = _config_dir / "api.conf"
    if not api_conf.exists():
        return RedirectResponse("/wizard", status_code=303)

    # API connection info for the landing card
    from weewx_clearskies_config.wizard.known_apis import load_known_apis

    known = load_known_apis(_config_dir)
    connection_url = next(iter(known), "")
    api_section = get_section("api", "api", _config_dir)
    connection_bind = (
        f"{api_section.get('bind_host', '')}:{api_section.get('bind_port', '8765')}"
        if api_section.get("bind_host")
        else ""
    )

    # Read current values for all sections shown on the landing page.
    # Provider sections are fetched from the API (authoritative, on the weewx
    # host) with local-file fallback.  Non-provider sections read locally.
    api_providers = _fetch_api_providers()
    branding = read_branding(_config_dir)
    pages_data = read_pages(_config_dir)
    ui_values = get_section("stack", "ui", _config_dir)
    db_values = get_section("api", "database", _config_dir)
    forecast_values = api_providers.get("forecast") or get_section("api", "forecast", _config_dir)
    alerts_values = api_providers.get("alerts") or get_section("api", "alerts", _config_dir)
    aqi_values = api_providers.get("aqi") or get_section("api", "aqi", _config_dir)
    earthquakes_section = api_providers.get("earthquakes") or get_section("api", "earthquakes", _config_dir)
    radar_values = api_providers.get("radar") or get_section("api", "radar", _config_dir)
    webcam_values = get_section("stack", "webcam", _config_dir)
    stack_earthquakes = _get_with_defaults(
        get_section("stack", "earthquakes", _config_dir), _EARTHQUAKE_DEFAULTS
    )
    tls_values = get_section("stack", "tls", _config_dir)
    sky_values = _get_with_defaults(
        get_section("api", "sky_classification", _config_dir), _SKY_DEFAULTS
    )
    haze_values = _get_with_defaults(
        get_section("api", "conditions", _config_dir), _HAZE_DEFAULTS
    )
    haze_calibration = _read_calibration_state()
    hidden_pages: list[str] = pages_data.get("hidden", [])

    return _render(
        request,
        "landing.html",
        {
            "branding": branding,
            "hidden_pages": hidden_pages,
            "all_pages": _ALL_PAGES,
            "ui_values": ui_values,
            "db_values": db_values,
            "forecast_values": forecast_values,
            "alerts_values": alerts_values,
            "aqi_values": aqi_values,
            "earthquakes_provider": earthquakes_section,
            "radar_values": radar_values,
            "webcam_values": webcam_values,
            "stack_earthquakes": stack_earthquakes,
            "tls_values": tls_values,
            "sky_values": sky_values,
            "haze_values": haze_values,
            "haze_calibration": haze_calibration,
            "connection_url": connection_url,
            "connection_bind": connection_bind,
        },
    )


# ---------------------------------------------------------------------------
# T3.2 — Page visibility
# ---------------------------------------------------------------------------


@router.get("/pages", response_class=HTMLResponse)
async def pages_get(request: Request) -> HTMLResponse:
    """Render the page visibility edit form."""
    _require_session(request)
    assert _config_dir is not None

    pages_data = read_pages(_config_dir)
    hidden: list[str] = pages_data.get("hidden", [])

    return _render(
        request,
        "pages_visibility.html",
        {
            "pages": _ALL_PAGES,
            "hidden": hidden,
        },
    )


@router.post("/pages", response_class=HTMLResponse)
async def pages_post(request: Request) -> HTMLResponse:
    """Save page visibility and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    # "visible" is a multi-value field; each checked checkbox submits its slug.
    visible_slugs = set(form.getlist("visible"))
    # "now" is always visible regardless of form submission
    visible_slugs.add("now")

    all_slugs = {p["slug"] for p in _ALL_PAGES}
    hidden = sorted(all_slugs - visible_slugs)

    error: str | None = None
    success = False
    try:
        update_pages(_config_dir, hidden)
        success = True
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("pages_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving page visibility: {exc}"
        logger.exception("pages_post unexpected error")

    return _render_result(
        request,
        section_slug="pages",
        display_name="Page Visibility",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.3 — Branding (appearance)
# ---------------------------------------------------------------------------


@router.get("/branding", response_class=HTMLResponse)
async def branding_get(request: Request) -> HTMLResponse:
    """Render the appearance/branding edit form."""
    _require_session(request)
    assert _config_dir is not None

    branding = read_branding(_config_dir)
    return _render(
        request,
        "branding.html",
        {
            "branding": branding,
            "accent_options": _ACCENT_OPTIONS,
            "theme_options": _THEME_OPTIONS,
        },
    )


@router.post("/branding", response_class=HTMLResponse)
async def branding_post(request: Request) -> HTMLResponse:
    """Save appearance/branding fields and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    # Allowed keys only — input validation at trust boundary
    updates: dict[str, Any] = {}
    site_title = str(form.get("siteTitle", "")).strip()
    updates["siteTitle"] = site_title

    copyright_entity = str(form.get("copyrightEntity", "")).strip()
    updates["copyrightEntity"] = copyright_entity

    accent = str(form.get("accent", "")).strip()
    if accent in _ACCENT_OPTIONS:
        updates["accent"] = accent

    theme_mode = str(form.get("defaultThemeMode", "")).strip()
    if theme_mode in _THEME_OPTIONS:
        updates["defaultThemeMode"] = theme_mode

    favicon_url = str(form.get("faviconUrl", "")).strip()
    updates["faviconUrl"] = favicon_url

    custom_css_url = str(form.get("customCssUrl", "")).strip()
    updates["customCssUrl"] = custom_css_url or None

    # Logo URLs — stored nested under "logo"
    logo_light = str(form.get("logo.lightUrl", "")).strip()
    logo_dark = str(form.get("logo.darkUrl", "")).strip()
    logo_alt = str(form.get("logo.alt", "")).strip()
    updates["logo"] = {
        "lightUrl": logo_light,
        "darkUrl": logo_dark,
        "alt": logo_alt,
    }

    error: str | None = None
    success = False
    try:
        update_branding(_config_dir, updates)
        success = True
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("branding_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving branding: {exc}"
        logger.exception("branding_post unexpected error")

    return _render_result(
        request,
        section_slug="branding",
        display_name="Appearance",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.3 — Social links
# ---------------------------------------------------------------------------


@router.get("/social", response_class=HTMLResponse)
async def social_get(request: Request) -> HTMLResponse:
    """Render the social links edit form."""
    _require_session(request)
    assert _config_dir is not None

    branding = read_branding(_config_dir)
    social = branding.get("social", {})
    return _render(
        request,
        "social.html",
        {"social": social},
    )


@router.post("/social", response_class=HTMLResponse)
async def social_post(request: Request) -> HTMLResponse:
    """Save social links and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    social: dict[str, str] = {
        "facebook": str(form.get("facebook", "")).strip(),
        "twitter": str(form.get("twitter", "")).strip(),
        "instagram": str(form.get("instagram", "")).strip(),
        "youtube": str(form.get("youtube", "")).strip(),
    }

    error: str | None = None
    success = False
    try:
        update_branding(_config_dir, {"social": social})
        success = True
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("social_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving social links: {exc}"
        logger.exception("social_post unexpected error")

    return _render_result(
        request,
        section_slug="social",
        display_name="Social Links",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.3 — Analytics & Privacy
# ---------------------------------------------------------------------------


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_get(request: Request) -> HTMLResponse:
    """Render the analytics & privacy edit form."""
    _require_session(request)
    assert _config_dir is not None

    branding = read_branding(_config_dir)
    return _render(
        request,
        "analytics_privacy.html",
        {
            "ga_id": branding.get("googleAnalyticsId", ""),
            "privacy_regions": branding.get("privacyRegions", "global"),
        },
    )


@router.post("/analytics", response_class=HTMLResponse)
async def analytics_post(request: Request) -> HTMLResponse:
    """Save analytics & privacy settings and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()
    ga_id = str(form.get("googleAnalyticsId", "")).strip()
    privacy_regions = str(form.get("privacyRegions", "global")).strip()

    error: str | None = None
    success = False
    try:
        update_branding(
            _config_dir,
            {
                "googleAnalyticsId": ga_id,
                "privacyRegions": privacy_regions,
            },
        )
        success = True
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("analytics_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving analytics settings: {exc}"
        logger.exception("analytics_post unexpected error")

    return _render_result(
        request,
        section_slug="analytics",
        display_name="Analytics & Privacy",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.4 — Earthquake feature settings
# ---------------------------------------------------------------------------


@router.get("/earthquakes", response_class=HTMLResponse)
async def earthquakes_get(request: Request) -> HTMLResponse:
    """Render the earthquake feature settings edit form."""
    _require_session(request)
    assert _config_dir is not None

    values = _get_with_defaults(
        get_section("stack", "earthquakes", _config_dir), _EARTHQUAKE_DEFAULTS
    )
    return _render(request, "feature_settings.html", {"values": values})


@router.post("/earthquakes", response_class=HTMLResponse)
async def earthquakes_post(request: Request) -> HTMLResponse:
    """Save earthquake settings and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    # Validate numeric fields — accept only values that look like numbers
    def _safe_num(key: str, default: str) -> str:
        raw = str(form.get(key, "")).strip()
        if raw:
            try:
                float(raw)
                return raw
            except ValueError:
                pass
        return default

    values = {
        "radius_km": _safe_num("radius_km", _EARTHQUAKE_DEFAULTS["radius_km"]),
        "min_magnitude": _safe_num("min_magnitude", _EARTHQUAKE_DEFAULTS["min_magnitude"]),
        "default_days": _safe_num("default_days", _EARTHQUAKE_DEFAULTS["default_days"]),
    }

    stack_conf = _config_dir / "stack.conf"
    error: str | None = None
    success = False
    try:
        if not stack_conf.exists():
            raise FileNotFoundError("stack.conf not found — run the setup wizard first.")
        update_managed_region(stack_conf, "earthquakes", values)
        success = True
    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("earthquakes_post FileNotFoundError: %s", exc)
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("earthquakes_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving earthquake settings: {exc}"
        logger.exception("earthquakes_post unexpected error")

    return _render_result(
        request,
        section_slug="earthquakes",
        display_name="Earthquake Settings",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.4 — TLS settings
# ---------------------------------------------------------------------------


@router.get("/tls", response_class=HTMLResponse)
async def tls_get(request: Request) -> HTMLResponse:
    """Render the TLS settings edit form."""
    _require_session(request)
    assert _config_dir is not None

    values = get_section("stack", "tls", _config_dir)
    return _render(
        request,
        "tls.html",
        {
            "values": values,
            "tls_modes": _TLS_MODES,
        },
    )


@router.post("/tls", response_class=HTMLResponse)
async def tls_post(request: Request) -> HTMLResponse:
    """Save TLS settings and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    allowed_modes = {m["value"] for m in _TLS_MODES}
    mode = str(form.get("mode", "self-signed")).strip()
    if mode not in allowed_modes:
        mode = "self-signed"

    values: dict[str, str] = {"mode": mode}

    if mode in ("acme_http01", "acme_dns01"):
        domain = str(form.get("domain", "")).strip()
        acme_email = str(form.get("acme_email", "")).strip()
        if domain:
            values["domain"] = domain
        if acme_email:
            values["acme_email"] = acme_email

    if mode == "acme_dns01":
        dns_provider = str(form.get("dns_provider", "")).strip()
        if dns_provider:
            values["dns_provider"] = dns_provider

    if mode == "manual":
        cert_path = str(form.get("tls_cert_path", "")).strip()
        key_path = str(form.get("tls_key_path", "")).strip()
        if cert_path:
            values["tls_cert_path"] = cert_path
        if key_path:
            values["tls_key_path"] = key_path

    stack_conf = _config_dir / "stack.conf"
    error: str | None = None
    success = False
    try:
        if not stack_conf.exists():
            raise FileNotFoundError("stack.conf not found — run the setup wizard first.")
        update_managed_region(stack_conf, "tls", values)
        success = True
    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("tls_post FileNotFoundError: %s", exc)
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("tls_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving TLS settings: {exc}"
        logger.exception("tls_post unexpected error")

    return _render_result(
        request,
        section_slug="tls",
        display_name="TLS Settings",
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
        error = "API URL is required."
    elif not api_url.startswith("https://"):
        error = "API URL must start with https://"

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
            error = f"File write error: {exc}"
            logger.error("connection_post OSError: %s", exc)
        except subprocess.CalledProcessError as exc:
            error = f"Caddy reload failed: {exc.stderr.decode() if exc.stderr else exc}"
            logger.error("connection_post Caddy reload failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            error = f"Unexpected error: {exc}"
            logger.exception("connection_post unexpected error")

    return _render_result(
        request,
        section_slug="connection",
        display_name="API Connection",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )


# ---------------------------------------------------------------------------
# T3.5 — Sky Classification calibration
# ---------------------------------------------------------------------------


@router.get("/sky-classification", response_class=HTMLResponse)
async def sky_classification_get(request: Request) -> HTMLResponse:
    """Render the sky classification calibration form."""
    _require_session(request)
    assert _config_dir is not None

    values = _get_with_defaults(
        get_section("api", "sky_classification", _config_dir), _SKY_DEFAULTS
    )
    return _render(
        request,
        "sky_classification.html",
        {
            "values": values,
            "kc_reference": _KC_REFERENCE,
            "defaults": _SKY_DEFAULTS,
        },
    )


@router.post("/sky-classification", response_class=HTMLResponse)
async def sky_classification_post(request: Request) -> HTMLResponse:
    """Save sky classification thresholds and return result fragment."""
    _require_session(request)
    assert _config_dir is not None

    form = await request.form()

    def _safe_float(key: str) -> str:
        raw = str(form.get(key, "")).strip()
        if raw:
            try:
                float(raw)
                return raw
            except ValueError:
                pass
        return _SKY_DEFAULTS[key]

    # Handle reset-to-defaults
    if form.get("reset") == "1":
        values = dict(_SKY_DEFAULTS)
    else:
        values = {
            "scatter_few_max": _safe_float("scatter_few_max"),
            "scatter_sct_max": _safe_float("scatter_sct_max"),
            "scatter_bkn_max": _safe_float("scatter_bkn_max"),
            "overcast_km_threshold": _safe_float("overcast_km_threshold"),
            "overcast_kv_threshold": _safe_float("overcast_kv_threshold"),
            "sza_min_elevation": _safe_float("sza_min_elevation"),
        }

    api_conf = _config_dir / "api.conf"
    error: str | None = None
    success = False
    try:
        if not api_conf.exists():
            raise FileNotFoundError("api.conf not found — run the setup wizard first.")
        update_managed_region(api_conf, "sky_classification", values)
        success = True
    except FileNotFoundError as exc:
        error = str(exc)
        logger.warning("sky_classification_post FileNotFoundError: %s", exc)
    except OSError as exc:
        error = f"File write error: {exc}"
        logger.error("sky_classification_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving sky classification: {exc}"
        logger.exception("sky_classification_post unexpected error")

    return _render_result(
        request,
        section_slug="sky-classification",
        display_name="Sky Classification",
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
        error = "Cannot connect to API."
    else:
        try:
            response = client._request("GET", "/setup/openaq-sensors")
            data = response.json()
            sensors = data.get("sensors", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("openaq_sensors_fragment: could not load sensors: %s", exc)
            error = f"Could not load sensors: {exc}"

    if error:
        escaped = error.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return HTMLResponse(
            f'<p style="font-size:0.875rem;color:var(--pico-del-color)">{escaped}</p>'
        )
    if not sensors:
        return HTMLResponse(
            '<p style="font-size:0.875rem;color:var(--pico-muted-color)">'
            "No reference sensors found within 25 km.</p>"
        )

    def _esc(v: object) -> str:
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    options = ['<option value="">— Select a sensor —</option>']
    for s in sensors:
        sensor_id = _esc(s.get("sensor_id", ""))
        label = _esc(
            f"{s.get('name', '?')} ({float(s.get('distance_km', 0)):.1f} km, ID: {s.get('sensor_id', '?')})"
        )
        options.append(f'<option value="{sensor_id}">{label}</option>')

    select_html = (
        '<label for="sensor-select" style="font-size:0.875rem">Reference sensors nearby</label>'
        '<select id="sensor-select" aria-label="Select a reference sensor"'
        ' onchange="document.getElementById(\'manual_sensor_id\').value = this.value">'
        + "".join(options)
        + "</select>"
        '<small style="display:block;margin-block:0.25rem">Select a sensor to populate'
        " the ID field below, then click “Set sensor override.”"
        " Only reference-grade (AQMD/regulatory) monitors are listed.</small>"
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
        error = f"File write error: {exc}"
        logger.error("haze_calibration_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error: {exc}"
        logger.exception("haze_calibration_post unexpected error")
    return _render_result(request, section_slug="haze-calibration",
        display_name="Haze Calibration", success=success, error=error,
        status_code=500 if error else 200)


@router.post("/haze-calibration/reset", response_class=HTMLResponse)
async def haze_calibration_reset(request: Request) -> HTMLResponse:
    """Reset calibration data via the API and return result fragment."""
    _require_session(request)
    client = _get_api_client()
    error: str | None = None
    success = False
    if client is None:
        error = "Cannot connect to API — check that the API is running and configured."
    else:
        try:
            response = client._request("POST", "/setup/calibration-reset")
            data = response.json()
            success = data.get("success", False)
            if not success:
                error = data.get("message", "Reset failed — unknown error.")
        except Exception as exc:  # noqa: BLE001
            error = f"API error: {exc}"
            logger.warning("calibration_reset API error: %s", exc)
    return _render_result(request, section_slug="haze-calibration",
        display_name="Haze Calibration", success=success, error=error,
        status_code=500 if error else 200)


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
            display_name="Now Page Layout",
            success=False,
            error="Invalid layout data",
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
        error = f"File write error: {exc}"
        logger.error("now_layout_post OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        error = f"Unexpected error saving card layout: {exc}"
        logger.exception("now_layout_post unexpected error")

    return _render_result(
        request,
        section_slug="now-layout",
        display_name="Now Page Layout",
        success=success,
        error=error,
        status_code=500 if error else 200,
    )

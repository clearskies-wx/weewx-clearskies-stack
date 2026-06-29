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
  GET  /admin/section/sky_classification — sky classification calibration form (custom template)
  POST /admin/section/sky_classification — save api.conf [sky_classification] (generic handler)
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
    update_managed_region,
)

logger = logging.getLogger(__name__)

# Haze calibration defaults
_HAZE_DEFAULTS: dict[str, str] = {
    "haze_detection": "true",
    "gamma": "0.45",
    "openaq_sensor_id": "",
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
        error = f"Error saving: {exc}"
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

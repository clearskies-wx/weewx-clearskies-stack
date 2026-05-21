"""FastAPI router for the 7-step setup wizard.

All endpoints require an authenticated session (session cookie set by the
login flow in app.py).  The wizard uses HTMX: forms post via hx-post, and
routes return HTML fragments when the HX-Request header is present.

Route summary:
  GET  /wizard                  — full wizard page (step 1)
  GET  /wizard/step/1           — step 1 fragment (API connection)
  POST /wizard/step/1           — verify fingerprint + handshake, return step 2 fragment
  GET  /wizard/step/2           — step 2 fragment (DB connection); pre-fills from API defaults
  POST /wizard/step/2/test      — test DB connection via API, return result fragment
  POST /wizard/step/2           — save DB settings, fetch schema via API, return step 3 or 4 fragment
  GET  /wizard/step/3           — render column mapping form using schema from state or API
  POST /wizard/step/3           — save column mapping, return step 4 fragment
  GET  /wizard/step/4           — read station identity from API, render step 4 fragment
  POST /wizard/step/4/timezone  — lookup timezone from lat/lon, return input fragment
  POST /wizard/step/4           — save station info, return step 5 fragment
  GET  /wizard/step/5           — data pipeline / MQTT, render step 5 fragment
  POST /wizard/step/5/test      — test MQTT broker connection, return result fragment
  POST /wizard/step/5           — save input mode + MQTT settings, return step 6 fragment
  GET  /wizard/step/6           — provider selection + inline key entry, render step 6 fragment
  GET  /wizard/step/6/key-fields/{domain}/{provider_id} — inline key fields fragment
  POST /wizard/step/6/test-key/{provider_id}            — test one provider's key, return result fragment
  POST /wizard/step/6           — save provider choices + keys, return step 7 fragment
  GET  /wizard/step/7           — review summary, render step 7 fragment
  POST /wizard/apply            — send config to API, write local config files, render completion page
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from weewx_clearskies_config.auth import COOKIE_NAME, SessionManager
from weewx_clearskies_config.wizard.api_client import ApiClient, ApiClientError
from weewx_clearskies_config.wizard.config_writer import apply_wizard
from weewx_clearskies_config.wizard.known_apis import load_known_apis, verify_or_pin_fingerprint
from weewx_clearskies_config.wizard.providers import (
    get_provider,
    providers_by_domain,
    recommend_providers,
    test_provider,
)
from weewx_clearskies_config.wizard.schema import (
    _ALL_CANONICAL_NAMES,
    canonical_groups,
    process_api_schema,
)
from weewx_clearskies_config.wizard.state import (
    WizardState,
    clear_wizard_state,
    configure_state_persistence,
    get_wizard_state,
    save_wizard_state,
)
from weewx_clearskies_config.wizard.station import lookup_timezone
from weewx_clearskies_config.wizard.topology import generate_proxy_secret

# ---------------------------------------------------------------------------
# Timezone list helper
# ---------------------------------------------------------------------------

# Prefixes to exclude from the dropdown — these are deprecated or
# system-specific zones that are not useful to operators.
_TZ_EXCLUDE_PREFIXES = (
    "Etc/",
    "SystemV/",
    "US/",    # aliases; operators should use America/*
    "Canada/",
    "Mexico/",
    "Brazil/",
    "Chile/",
    "Cuba",
    "Egypt",
    "Eire",
    "Factory",
    "GB",
    "Greenwich",
    "Hongkong",
    "Iceland",
    "Iran",
    "Israel",
    "Jamaica",
    "Japan",
    "Kwajalein",
    "Libya",
    "MET",
    "MST",
    "MST7MDT",
    "NZ",
    "Navajo",
    "Poland",
    "Portugal",
    "ROC",
    "ROK",
    "Singapore",
    "Turkey",
    "UCT",
    "UTC",
    "Universal",
    "W-SU",
    "Zulu",
    "WET",
    "CET",
    "EET",
    "EST",
    "EST5EDT",
    "CST6CDT",
    "PST8PDT",
    "HST",
    "posix/",
    "right/",
)

# Preferred region ordering for the optgroups.
_REGION_ORDER = [
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
]


def _build_timezone_list() -> list[tuple[str, list[str]]]:
    """Return a sorted list of (region, [timezone_name, ...]) tuples.

    Uses ``zoneinfo.available_timezones()`` (Python 3.9+ stdlib) to enumerate
    all IANA zone names.  Deprecated and system aliases are filtered out.
    Regions appear in the preferred order defined by ``_REGION_ORDER``; any
    remaining regions follow alphabetically.
    """
    try:
        from zoneinfo import available_timezones
    except ImportError:
        # Python < 3.9: fall back to an empty list; the template will render
        # a plain-text input as a fallback.
        return []

    all_zones = sorted(available_timezones())
    grouped: dict[str, list[str]] = {}

    for tz in all_zones:
        # Filter out deprecated / non-operator zones.
        skip = False
        for prefix in _TZ_EXCLUDE_PREFIXES:
            if tz == prefix.rstrip("/") or tz.startswith(prefix):
                skip = True
                break
        if skip:
            continue

        # Group by the part before the first slash; zones with no slash go
        # into "Other" (e.g. "UTC" if not filtered, "WET" etc.)
        region = tz.split("/", 1)[0] if "/" in tz else "Other"
        grouped.setdefault(region, []).append(tz)

    # Sort zones within each region.
    for region in grouped:
        grouped[region].sort()

    # Order regions: preferred list first, then alphabetically.
    ordered_regions = [r for r in _REGION_ORDER if r in grouped]
    remaining = sorted(r for r in grouped if r not in _REGION_ORDER)
    ordered_regions.extend(remaining)

    return [(region, grouped[region]) for region in ordered_regions]


# Build once at module load; the list is static.
_TIMEZONE_LIST: list[tuple[str, list[str]]] = _build_timezone_list()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wizard", tags=["wizard"])


def _get_api_client(state: WizardState) -> ApiClient:
    """Create an API client from wizard state.

    Supports two authentication modes:

    - **Session mode** (first run): uses ``state.api_session_id`` acquired from
      the handshake call in step 1.
    - **Proxy-auth mode** (re-run): uses ``state.proxy_secret`` from the local
      secrets.env when setup is already complete and no session has been
      established.

    Raises:
        ValueError: If neither api_address nor a valid auth credential is
            available (step 1 has not been completed in either mode).
    """
    if not state.api_address:
        raise ValueError("API not connected")
    if state.api_session_id:
        return ApiClient(state.api_address, session_id=state.api_session_id)
    if state.proxy_secret:
        return ApiClient(state.api_address, proxy_secret=state.proxy_secret)
    raise ValueError("API not connected")


def _is_rerun_mode(api_address: str | None) -> bool:
    """Return True if *api_address* has a stored fingerprint AND the proxy secret exists.

    Both conditions are required: a stored fingerprint means step 1 was completed
    before, and the proxy secret means the full wizard completed (Apply wrote it
    to secrets.env).  Without the proxy secret, we fall back to first-run mode
    so the operator can use a trust token instead.
    """
    if not api_address or _config_dir is None:
        return False
    from weewx_clearskies_config.wizard.known_apis import get_known_fingerprint
    if get_known_fingerprint(_config_dir, api_address) is None:
        return False
    from weewx_clearskies_config.wizard.state_persistence import _read_secrets_env
    secrets = _read_secrets_env(_config_dir)
    return bool(secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET"))


def _api_error_message(exc: ApiClientError) -> str:
    """Map an ApiClientError to a user-friendly plain-English message."""
    if exc.status_code == 401:
        return "Your setup session has expired. Go back to step 1 and reconnect to the API."
    if exc.status_code == 410:
        return "This API has already been set up. If you need to reconfigure it, restart the API with the --reset flag."
    if exc.status_code == 503:
        return "The API is temporarily unavailable. Wait a moment and try again."
    return f"The API returned an error ({exc.status_code}). Check the API server log and try again."

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


def _split_api_address(api_address: str) -> tuple[str, str]:
    """Split a stored ``https://{host}:{port}`` URL back into (host, port) strings.

    Returns ("", "8765") if the address is blank or cannot be parsed.
    """
    if not api_address:
        return "", "8765"
    # Strip the scheme prefix produced by step1_api_post.
    addr = api_address
    if addr.startswith("https://"):
        addr = addr[len("https://"):]
    # The host may be a bare IPv6 literal ("[::1]") or a host:port pair.
    if addr.startswith("["):
        # IPv6 bracketed literal — find the closing bracket.
        close = addr.find("]")
        if close != -1:
            host = addr[1:close]
            rest = addr[close + 1:]
            port = rest.lstrip(":") or "8765"
            return host, port
    # Plain host or host:port.
    if ":" in addr:
        host, _, port = addr.rpartition(":")
        return host, port or "8765"
    return addr, "8765"


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def wizard_index(request: Request) -> HTMLResponse:
    """Render the full wizard page with step 1 (API connection) loaded."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    # Fresh-browser case: the session is new so state fields are blank, but a
    # previous session may have made progress.  Two recovery paths:
    #
    # 1. wizard_progress_*.json exists — merge its data into the current session so
    #    API credentials, DB settings, column mappings, and station info are
    #    restored.  Only fills fields that are still at their defaults (never
    #    overwrites data the user has already typed in the new session).
    # 2. known_apis.json exists but no progress file — pre-populate api_address
    #    from the pinned fingerprint store alone.
    if not state.api_address and _config_dir is not None:
        from weewx_clearskies_config.wizard.state_persistence import load_most_recent_progress
        prior = load_most_recent_progress(_config_dir)
        if prior is not None:
            # Merge: only fill blank fields in state from the prior session.
            # api_session_id is intentionally excluded — it expires with the old session.
            if not state.api_address and prior.api_address:
                state.api_address = prior.api_address
            if not state.cert_fingerprint and prior.cert_fingerprint:
                state.cert_fingerprint = prior.cert_fingerprint
            if state.db_host is None and prior.db_host is not None:
                state.db_host = prior.db_host
            if state.db_port == 3306 and prior.db_port != 3306:
                state.db_port = prior.db_port
            if state.db_user is None and prior.db_user is not None:
                state.db_user = prior.db_user
            if state.db_password is None and prior.db_password is not None:
                state.db_password = prior.db_password
            if state.db_name == "weewx" and prior.db_name != "weewx":
                state.db_name = prior.db_name
            if not state.column_mapping and prior.column_mapping:
                state.column_mapping = prior.column_mapping
            if state.station_name is None and prior.station_name is not None:
                state.station_name = prior.station_name
            if state.latitude is None and prior.latitude is not None:
                state.latitude = prior.latitude
            if state.longitude is None and prior.longitude is not None:
                state.longitude = prior.longitude
            if state.altitude_meters is None and prior.altitude_meters is not None:
                state.altitude_meters = prior.altitude_meters
            if state.timezone is None and prior.timezone is not None:
                state.timezone = prior.timezone
            if not state.providers and prior.providers:
                state.providers = prior.providers
            if not state.api_keys and prior.api_keys:
                state.api_keys = prior.api_keys
            if state.input_mode == "direct" and prior.input_mode != "direct":
                state.input_mode = prior.input_mode
            if not state.mqtt_broker_host and prior.mqtt_broker_host:
                state.mqtt_broker_host = prior.mqtt_broker_host
            if state.mqtt_broker_port == 1883 and prior.mqtt_broker_port != 1883:
                state.mqtt_broker_port = prior.mqtt_broker_port
            if state.mqtt_topic == "weewx/loop" and prior.mqtt_topic != "weewx/loop":
                state.mqtt_topic = prior.mqtt_topic
            if state.mqtt_client_id == "weewx-clearskies-realtime" and prior.mqtt_client_id != "weewx-clearskies-realtime":
                state.mqtt_client_id = prior.mqtt_client_id
            if not state.mqtt_username and prior.mqtt_username:
                state.mqtt_username = prior.mqtt_username
            if not state.mqtt_password and prior.mqtt_password:
                state.mqtt_password = prior.mqtt_password
            if not state.mqtt_tls and prior.mqtt_tls:
                state.mqtt_tls = prior.mqtt_tls
            if state.topology == "same-host" and prior.topology != "same-host":
                state.topology = prior.topology
            if state.proxy_secret is None and prior.proxy_secret is not None:
                state.proxy_secret = prior.proxy_secret
            if state.api_bind_host == "127.0.0.1" and prior.api_bind_host != "127.0.0.1":
                state.api_bind_host = prior.api_bind_host
            if state.api_bind_port == 8765 and prior.api_bind_port != 8765:
                state.api_bind_port = prior.api_bind_port
            if state.realtime_bind_host == "127.0.0.1" and prior.realtime_bind_host != "127.0.0.1":
                state.realtime_bind_host = prior.realtime_bind_host
            if state.realtime_bind_port == 8766 and prior.realtime_bind_port != 8766:
                state.realtime_bind_port = prior.realtime_bind_port
            save_wizard_state(session_id, state)
            logger.info("Restored wizard progress from prior session into session %s", session_id[:8])
        else:
            known = load_known_apis(_config_dir)
            if known:
                # Use the first (typically only) pinned API URL.
                state.api_address = next(iter(known))
                save_wizard_state(session_id, state)

    api_host, api_port = _split_api_address(state.api_address or "")
    rerun = _is_rerun_mode(state.api_address)
    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/layout.html",
        context={
            "step": 1,
            "state": state,
            "success": False,
            "api_host": api_host,
            "api_port": api_port,
            "rerun_mode": rerun,
        },
    )


# ---------------------------------------------------------------------------
# Step 1: API Connection
# ---------------------------------------------------------------------------


@router.get("/step/1", response_class=HTMLResponse)
async def step1_api_get(request: Request) -> HTMLResponse:
    """Step 1: Connect to API — show the connection form."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    api_host, api_port = _split_api_address(state.api_address or "")
    rerun = _is_rerun_mode(state.api_address)
    return _render(
        request,
        "step_api.html",
        {"step": 1, "state": state, "error": None, "success": False,
         "api_host": api_host, "api_port": api_port, "rerun_mode": rerun},
    )


@router.post("/step/1", response_class=HTMLResponse)
async def step1_api_post(request: Request) -> HTMLResponse:
    """Step 1: Connect to API — verify fingerprint + handshake, show success feedback.

    Two modes:

    - **First run**: operator provides a trust token and certificate fingerprint.
      The wizard exchanges the token for a setup session ID (handshake) and
      pins the fingerprint in known_apis.json.

    - **Re-run**: setup was completed before; the fingerprint is already stored
      in known_apis.json and the proxy secret is in secrets.env.  The trust
      token is not required.  The wizard verifies the live fingerprint still
      matches the stored pin, then uses X-Clearskies-Proxy-Auth for all
      subsequent API calls.
    """
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)

    host = str(form.get("api_host", "")).strip()
    port_raw = str(form.get("api_port", "8765")).strip() or "8765"
    trust_token = str(form.get("trust_token", "")).strip()
    cert_fingerprint = str(form.get("cert_fingerprint", "")).strip()

    # Validate host is always required.
    if not host:
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state,
             "error": "API host is required.",
             "success": False, "api_host": host, "api_port": port_raw,
             "rerun_mode": _is_rerun_mode(state.api_address)},
            status_code=422,
        )

    # Normalise port — must be an integer in 1–65535.
    port = _parse_int(port_raw, default=8765)
    if not (1 <= port <= 65535):
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state, "error": "Port must be between 1 and 65535.",
             "success": False, "api_host": host, "api_port": port_raw,
             "rerun_mode": _is_rerun_mode(state.api_address)},
            status_code=422,
        )

    api_address = f"https://{host}:{port}"
    assert _config_dir is not None, "config_dir not set — wizard router not initialised"

    # Detect which mode we are in before doing anything else.
    rerun = _is_rerun_mode(api_address)

    if rerun:
        # Re-run mode: verify the fingerprint is still pinned (no operator input
        # needed for the fingerprint itself — we compare live vs. stored).
        # Fetch the proxy secret from secrets.env for auth.
        from weewx_clearskies_config.wizard.known_apis import get_known_fingerprint
        stored_fp = get_known_fingerprint(_config_dir, api_address) or ""
        ok, err_msg = verify_or_pin_fingerprint(_config_dir, api_address, stored_fp)
        if not ok:
            return _render(
                request,
                "step_api.html",
                {"step": 1, "state": state, "error": err_msg,
                 "success": False, "api_host": host, "api_port": str(port),
                 "rerun_mode": True},
                status_code=422,
            )

        # Load the proxy secret from secrets.env so subsequent API calls can use
        # X-Clearskies-Proxy-Auth.  If the secret is absent (edge case: operator
        # deleted secrets.env), fall back gracefully with a clear error.
        from weewx_clearskies_config.wizard.state_persistence import _read_secrets_env
        secrets = _read_secrets_env(_config_dir)
        proxy_secret = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET") or state.proxy_secret
        if not proxy_secret:
            return _render(
                request,
                "step_api.html",
                {
                    "step": 1,
                    "state": state,
                    "error": (
                        "Re-run failed: the proxy secret is not in secrets.env. "
                        "If you deleted secrets.env, re-run the installer to regenerate it, "
                        "or restart the API with --reset to start a fresh setup."
                    ),
                    "success": False,
                    "api_host": host,
                    "api_port": str(port),
                    "rerun_mode": True,
                },
                status_code=422,
            )

        # Verify the proxy secret works by probing the API health endpoint.
        try:
            client = ApiClient(api_address, proxy_secret=proxy_secret)
            client.get_db_defaults()  # Any authenticated endpoint will do.
        except ApiClientError as exc:
            if exc.status_code == 401:
                error_msg = (
                    "The API did not accept the proxy secret. "
                    "Check that secrets.env contains the correct WEEWX_CLEARSKIES_PROXY_SECRET "
                    "and that the API is running with the same value."
                )
            else:
                error_msg = f"Could not verify the API connection: {_api_error_message(exc)}"
            return _render(
                request,
                "step_api.html",
                {"step": 1, "state": state, "error": error_msg,
                 "success": False, "api_host": host, "api_port": str(port),
                 "rerun_mode": True},
                status_code=422,
            )
        except Exception:  # noqa: BLE001
            return _render(
                request,
                "step_api.html",
                {"step": 1, "state": state,
                 "error": "Could not reach the API. Check the address and try again.",
                 "success": False, "api_host": host, "api_port": str(port),
                 "rerun_mode": True},
                status_code=422,
            )

        # Success — store address and proxy secret; leave api_session_id unset so
        # _get_api_client() uses proxy-auth mode for all subsequent steps.
        state.api_address = api_address
        state.proxy_secret = proxy_secret
        # api_session_id is intentionally left as-is (may be None or stale —
        # _get_api_client prefers session_id when set, so clear it).
        state.api_session_id = None
        save_wizard_state(session_id, state)
        return _render(
            request,
            "step_api.html",
            {
                "step": 1,
                "state": state,
                "error": None,
                "success": True,
                "api_host": host,
                "api_port": str(port),
                "rerun_mode": True,
            },
        )

    # ------------------------------------------------------------------
    # First-run mode: trust token + fingerprint required.
    # ------------------------------------------------------------------
    if not trust_token or not cert_fingerprint:
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state, "error": "All fields are required.",
             "success": False, "api_host": host, "api_port": port_raw,
             "rerun_mode": False},
            status_code=422,
        )

    # Verify fingerprint (TOFU) — fetch the live cert and compare.
    ok, err_msg = verify_or_pin_fingerprint(_config_dir, api_address, cert_fingerprint)
    if not ok:
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state, "error": err_msg,
             "success": False, "api_host": host, "api_port": str(port),
             "rerun_mode": False},
            status_code=422,
        )

    # Handshake — exchange the one-time trust token for a setup session ID.
    try:
        client = ApiClient(api_address)
        api_session_id = client.handshake(trust_token)
    except ApiClientError as exc:
        if exc.status_code == 401:
            error_msg = "Invalid trust token. Check the token printed in the API terminal and try again."
        elif exc.status_code == 410:
            error_msg = "This API has already been set up. If you need to reconfigure it, restart the API with the --reset flag."
        else:
            error_msg = "Could not connect to the API. Check the address and try again."
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state, "error": error_msg,
             "success": False, "api_host": host, "api_port": str(port),
             "rerun_mode": False},
            status_code=422,
        )
    except Exception:  # noqa: BLE001
        return _render(
            request,
            "step_api.html",
            {"step": 1, "state": state,
             "error": "Could not reach the API. Check the address and try again.",
             "success": False, "api_host": host, "api_port": str(port),
             "rerun_mode": False},
            status_code=422,
        )

    # Success — store in wizard state and re-render step 1 with success feedback.
    # The operator sees a green confirmation and a "Continue" button.  This gives
    # clear evidence that the handshake worked before advancing to step 2.
    state.api_address = api_address
    state.api_session_id = api_session_id
    state.cert_fingerprint = cert_fingerprint
    save_wizard_state(session_id, state)
    return _render(
        request,
        "step_api.html",
        {
            "step": 1,
            "state": state,
            "error": None,
            "success": True,
            "api_host": host,
            "api_port": str(port),
            "rerun_mode": False,
        },
    )


# ---------------------------------------------------------------------------
# Step 2: DB connection
# ---------------------------------------------------------------------------


@router.get("/step/2", response_class=HTMLResponse)
async def step2_db_get(request: Request) -> HTMLResponse:
    """Step 2: DB connection — pre-fill form from API defaults or saved state."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    # Merge from existing config files (e.g. wizard re-run).
    if state.db_host is None:
        _merge_from_existing_config(state)

    # If still no DB info, ask the API for defaults from its weewx.conf.
    api_warning: str | None = None
    if state.db_host is None:
        try:
            client = _get_api_client(state)
            defaults = client.get_db_defaults()
            state.db_host = str(defaults.get("host", "localhost")) or "localhost"
            if defaults.get("port"):
                state.db_port = int(defaults["port"])
            if defaults.get("user"):
                state.db_user = str(defaults["user"])
            if defaults.get("db_name"):
                state.db_name = str(defaults["db_name"])
            # Never pre-fill the password from the API response — the operator
            # must enter it explicitly (the API doesn't transmit passwords).
        except ValueError:
            # API not connected yet — user navigated directly to step 2.
            pass
        except ApiClientError as exc:
            if exc.status_code == 401:
                # Session expired — redirect to step 1.
                return await step1_api_get(request)
            api_warning = "Could not fetch database defaults from the API. Enter the settings below."
            logger.warning("get_db_defaults failed: %s", exc)
        except Exception:  # noqa: BLE001
            api_warning = "Could not reach the API to fetch database defaults. Enter the settings below."
            logger.warning("get_db_defaults network error", exc_info=True)

    return _render(
        request,
        "step_db.html",
        {"step": 2, "state": state, "result": None, "error": api_warning},
    )


@router.post("/step/2/test", response_class=HTMLResponse)
async def step2_db_test(request: Request) -> HTMLResponse:
    """Test the DB connection via the API without saving; return a result fragment."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    form = await request.form()
    host = str(form.get("db_host", "localhost")).strip()
    port = _parse_int(str(form.get("db_port", "3306")), default=3306)
    user = str(form.get("db_user", "")).strip()
    password = str(form.get("db_password", ""))
    db_name = str(form.get("db_name", "weewx")).strip()

    result: dict[str, Any]
    try:
        client = _get_api_client(state)
        result = client.test_db(host, port, user, password, db_name)
    except ValueError:
        result = {"success": False, "error": "API not connected. Go back to step 1 and reconnect.", "version": None}
    except ApiClientError as exc:
        if exc.status_code == 401:
            result = {"success": False, "error": "Your setup session has expired. Go back to step 1 to reconnect.", "version": None}
        else:
            result = {"success": False, "error": _api_error_message(exc), "version": None}
    except Exception:  # noqa: BLE001
        result = {"success": False, "error": "Could not reach the API to test the connection. Check that the API is running and try again.", "version": None}

    return _render(
        request,
        "step_db_test_result.html",
        {"result": result},
    )


@router.post("/step/2", response_class=HTMLResponse)
async def step2_db_post(request: Request) -> HTMLResponse:
    """Save DB settings, fetch schema via API, advance to step 3 or 4."""
    session_id = _require_session(request)
    form = await request.form()
    state = get_wizard_state(session_id)
    state.db_host = str(form.get("db_host", "")).strip() or None
    state.db_port = _parse_int(str(form.get("db_port", "3306")), default=3306)
    state.db_user = str(form.get("db_user", "")).strip() or None
    # Password handling: the template sends db_password_unchanged=1 and an empty
    # password field when the user has not re-typed a password on re-render.
    # Only overwrite the stored secret when the user actually supplies a value.
    submitted_db_password = str(form.get("db_password", ""))
    db_password_unchanged = str(form.get("db_password_unchanged", "0")).strip() == "1"
    if submitted_db_password:
        state.db_password = submitted_db_password
    elif not db_password_unchanged:
        # Explicit blank entry with the flag cleared — user cleared the password.
        state.db_password = ""
    # else: flag is set and field is empty — keep existing state.db_password.
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

    # Persist the DB fields entered by the user so partial progress survives even
    # if the connection test or schema fetch fails (user can adjust and retry).
    save_wizard_state(session_id, state)

    # Test the connection via API before proceeding.
    try:
        client = _get_api_client(state)
        test_result = client.test_db(
            state.db_host or "",
            state.db_port,
            state.db_user or "",
            state.db_password or "",
            state.db_name,
        )
        if not test_result.get("success"):
            error_msg = f"Connection test failed: {test_result.get('error', 'unknown error')}"
            return _render(
                request,
                "step_db.html",
                {"step": 2, "state": state, "result": None, "error": error_msg},
                status_code=422,
            )
    except ValueError:
        return _render(
            request,
            "step_db.html",
            {"step": 2, "state": state, "result": None, "error": "API not connected. Go back to step 1 and reconnect."},
            status_code=422,
        )
    except ApiClientError as exc:
        if exc.status_code == 401:
            return await step1_api_get(request)
        return _render(
            request,
            "step_db.html",
            {"step": 2, "state": state, "result": None, "error": _api_error_message(exc)},
            status_code=422,
        )
    except Exception:  # noqa: BLE001
        return _render(
            request,
            "step_db.html",
            {"step": 2, "state": state, "result": None, "error": "Could not reach the API to test the connection. Check that the API is running and try again."},
            status_code=422,
        )

    # Fetch schema via API and process it.
    skip_schema = False
    try:
        api_schema = client.get_schema()
        schema_data = process_api_schema(api_schema)
        state.schema_data = schema_data
        if not schema_data.get("unmapped_columns"):
            # All columns are stock — auto-save the stock mapping and skip step 3.
            state.column_mapping = {
                col["db_name"]: col["canonical"]
                for col in schema_data.get("stock_columns", [])
            }
            skip_schema = True
    except ApiClientError as exc:
        # Schema fetch failed — fall through to step 3 so the user can review.
        logger.warning("get_schema failed in step2_db_post (%s): %s", exc.status_code, exc.detail)
        state.schema_data = None
    except Exception:  # noqa: BLE001
        logger.warning("get_schema network error in step2_db_post", exc_info=True)
        state.schema_data = None

    state.schema_skipped = skip_schema
    save_wizard_state(session_id, state)
    if skip_schema:
        return await step4_get(request)
    return await step3_get(request)


# ---------------------------------------------------------------------------
# Step 5: Data Pipeline (input mode / MQTT)
# ---------------------------------------------------------------------------


def _is_loopback(host: str) -> bool:
    """Return True if *host* refers to the local machine."""
    _LOOPBACK = {"localhost", "127.0.0.1", "::1", ""}
    return host.strip().lower() in _LOOPBACK


def _extract_host_from_url(url: str) -> str:
    """Extract the bare hostname from a ``https://host:port`` URL.

    Returns an empty string if the URL cannot be parsed.
    """
    addr = url or ""
    if addr.startswith("https://"):
        addr = addr[len("https://"):]
    if addr.startswith("["):
        close = addr.find("]")
        if close != -1:
            return addr[1:close]
        return ""
    host = addr.split(":")[0] if ":" in addr else addr
    return host.strip()


@router.get("/step/5", response_class=HTMLResponse)
async def step5_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    # On re-run, pre-populate MQTT settings from the existing realtime.conf if
    # the state does not already have them.  _merge_from_existing_config only
    # fills fields that are still at their defaults, so user edits are safe.
    if not state.mqtt_broker_host:
        _merge_from_existing_config(state)

    # Auto-detect the recommended live-update mode from what the wizard already knows.
    # Skip the auto-detect when existing config files are present — in re-run mode
    # _merge_from_existing_config already set state.input_mode from realtime.conf, and
    # overwriting that here would replace the user's configured value with the topology
    # heuristic (which might differ, e.g. a remote API host that uses direct-pipe mode).
    #
    # The relevant question is whether the API (weewx / loop-packet source) is on
    # the same physical machine as the config UI / realtime service (weather-dev).
    # The DB host is irrelevant — it may co-locate with the API on a completely
    # different machine and still require MQTT.
    #
    # Decision rule (first-run only):
    #   API host is loopback (localhost / 127.0.0.1 / ::1)
    #     → the API is on the same machine as the config UI → direct is possible
    #   API host is any non-loopback address
    #     → the API is on a remote machine → MQTT is required
    pipeline_hint: str | None = None
    if not _existing_configs_present():
        api_host = _extract_host_from_url(state.api_address or "").lower()
        if api_host:
            if _is_loopback(api_host):
                state.input_mode = "direct"
                pipeline_hint = (
                    "The Clear Skies API is on the same server as the config UI, "
                    "so live updates can connect directly."
                )
            else:
                state.input_mode = "mqtt"
                pipeline_hint = (
                    "The Clear Skies API is on a different server than the config UI, "
                    "so live updates need an MQTT message broker to bridge them."
                )

    return _render(
        request,
        "step_mqtt.html",
        {"step": 5, "state": state, "error": None, "test_result": None,
         "pipeline_hint": pipeline_hint},
    )


@router.post("/step/5/test", response_class=HTMLResponse)
async def step5_mqtt_test(request: Request) -> HTMLResponse:
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


@router.post("/step/5", response_class=HTMLResponse)
async def step5_post(request: Request) -> HTMLResponse:
    """Save input mode + MQTT settings and advance to step 6 (providers)."""
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
        # Password handling: the template sends password_unchanged=1 and an empty
        # password field when the user has not re-typed a password on re-render.
        # Only overwrite the stored secret when the user actually supplies a value.
        submitted_password = str(form.get("mqtt_password", ""))
        password_unchanged = str(form.get("password_unchanged", "0")).strip() == "1"
        if submitted_password:
            state.mqtt_password = submitted_password
        elif not password_unchanged:
            # Explicit blank entry with the flag cleared — user cleared the password.
            state.mqtt_password = ""
        # else: flag is set and field is empty — keep existing state.mqtt_password.
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
                {"step": 5, "state": state, "error": "; ".join(errors.values()),
                 "test_result": None, "pipeline_hint": None},
                status_code=422,
            )
    else:
        # Direct mode: reset all MQTT fields to defaults so stale values do not
        # bleed into the generated config if the user switches back to MQTT later.
        state.mqtt_broker_host = ""
        state.mqtt_broker_port = 1883
        state.mqtt_topic = "weewx/loop"
        state.mqtt_client_id = "weewx-clearskies-realtime"
        state.mqtt_username = ""
        state.mqtt_password = ""
        state.mqtt_tls = False
        state.mqtt_qos = 0
        state.mqtt_keepalive = 60

    save_wizard_state(session_id, state)
    return await step6_get(request)


# ---------------------------------------------------------------------------
# Step 3: Schema + Column Mapping
# ---------------------------------------------------------------------------


@router.get("/step/3", response_class=HTMLResponse)
async def step3_get(request: Request) -> HTMLResponse:
    """Step 3: Column mapping — use schema cached in state or re-fetch from API."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    if not state.column_mapping:
        _merge_from_existing_config(state)

    schema_data: dict[str, Any] | None = state.schema_data
    error: str | None = None

    # If schema wasn't cached (e.g. user navigated directly to step 3), fetch it.
    if schema_data is None:
        try:
            client = _get_api_client(state)
            api_schema = client.get_schema()
            schema_data = process_api_schema(api_schema)
            state.schema_data = schema_data
            save_wizard_state(session_id, state)
        except ValueError:
            error = "API not connected. Go back to step 1 and reconnect."
        except ApiClientError as exc:
            if exc.status_code == 401:
                return await step1_api_get(request)
            error = "Could not fetch the database schema from the API — check your connection settings in step 2 and try again."
            logger.warning("get_schema failed in step3_get: %s", exc)
        except Exception:  # noqa: BLE001
            error = "Could not reach the API to fetch the database schema. Check that the API is running and try again."
            logger.warning("get_schema network error in step3_get", exc_info=True)

    # If the user has previously saved column mappings (e.g. they advanced to step 4
    # then clicked Previous), overlay those choices onto the schema's suggested values
    # so the dropdowns pre-select what they chose rather than the heuristic suggestion.
    if schema_data is not None and state.column_mapping:
        for col in schema_data.get("unmapped_columns", []):
            saved = state.column_mapping.get(col["db_name"])
            if saved is not None:
                # saved may be "" (skip) or a canonical name — use it as the selection.
                col["suggested"] = saved or None
                col["confidence"] = "saved"

    return _render(
        request,
        "step_schema.html",
        {"step": 3, "state": state, "schema": schema_data, "error": error, "errors": {}, "canonical_groups": canonical_groups},
    )


@router.post("/step/3", response_class=HTMLResponse)
async def step3_post(request: Request) -> HTMLResponse:
    """Save column mapping choices and advance to step 4."""
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
        # Re-use schema data from state; fall back to API if not cached.
        schema_data: dict[str, Any] | None = state.schema_data
        schema_error: str | None = None
        if schema_data is None:
            try:
                client = _get_api_client(state)
                api_schema = client.get_schema()
                schema_data = process_api_schema(api_schema)
                state.schema_data = schema_data
            except Exception as exc:  # noqa: BLE001
                schema_error = "Could not read the database schema — check your connection settings in step 2 and try again."
                logger.warning("get_schema error in step3_post: %s", exc)
        return _render(
            request,
            "step_schema.html",
            {
                "step": 3,
                "state": state,
                "schema": schema_data,
                "error": schema_error,
                "errors": errors,
                "canonical_groups": canonical_groups,
            },
            status_code=422,
        )

    state.column_mapping = mapping
    state.schema_data = None  # Clear cached schema data — no longer needed.
    save_wizard_state(session_id, state)
    return await step4_get(request)


# ---------------------------------------------------------------------------
# Step 4: Station Identity
# ---------------------------------------------------------------------------


@router.get("/step/4", response_class=HTMLResponse)
async def step4_get(request: Request) -> HTMLResponse:
    """Step 4: Station identity — pre-fill from API (reads weewx.conf server-side)."""
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    error: str | None = None

    # Pre-fill from API only when station fields are still empty.
    if state.station_name is None:
        # Try existing config files first (wizard re-run).
        _merge_from_existing_config(state)

        # If the config merge gave us lat/lon but no timezone, auto-detect now.
        if state.latitude and state.longitude and not state.timezone:
            state.timezone = lookup_timezone(state.latitude, state.longitude)

    if state.station_name is None:
        # Ask the API to read weewx.conf server-side.
        try:
            client = _get_api_client(state)
            api_data = client.get_station()
            if api_data:
                if state.station_name is None:
                    state.station_name = api_data.get("station_name") or None
                if state.latitude is None:
                    state.latitude = _to_float(api_data.get("latitude"))
                if state.longitude is None:
                    state.longitude = _to_float(api_data.get("longitude"))
                if state.altitude_meters is None:
                    raw_alt = _to_float(api_data.get("altitude_meters"))
                    alt_unit = str(api_data.get("altitude_unit", "meter")).strip().lower()
                    # The API returns the raw numeric value from weewx.conf without
                    # converting units.  Convert feet → meters so state.altitude_meters
                    # is always in meters (matching the field name and step4_post logic).
                    if raw_alt is not None and ("foot" in alt_unit or "feet" in alt_unit or alt_unit == "ft"):
                        state.altitude_meters = raw_alt * 0.3048
                        state.altitude_unit = "feet"
                    else:
                        state.altitude_meters = raw_alt
                        state.altitude_unit = "meters"
                if state.timezone is None and api_data.get("timezone"):
                    state.timezone = str(api_data["timezone"])
                if state.latitude and state.longitude and not state.timezone:
                    state.timezone = lookup_timezone(state.latitude, state.longitude)
        except ValueError:
            # API not connected — show blank form (user navigated directly).
            pass
        except ApiClientError as exc:
            if exc.status_code == 401:
                return await step1_api_get(request)
            error = "Could not fetch station details from the API. Fill in the fields below manually."
            logger.warning("get_station failed in step4_get: %s", exc)
        except Exception:  # noqa: BLE001
            error = "Could not reach the API to fetch station details. Fill in the fields below manually."
            logger.warning("get_station network error in step4_get", exc_info=True)

    return _render(
        request,
        "step_station.html",
        {
            "step": 4,
            "state": state,
            "error": error,
            "schema_skipped": state.schema_skipped,
            "timezones": _TIMEZONE_LIST,
        },
    )


@router.post("/step/4", response_class=HTMLResponse)
async def step4_post(request: Request) -> HTMLResponse:
    """Save station identity and advance to step 5."""
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
        state.altitude_unit = "feet"
    else:
        state.altitude_meters = alt_raw
        state.altitude_unit = "meters"

    state.timezone = str(form.get("timezone", "")).strip() or None

    # Auto-lookup timezone if coordinates provided but timezone not set.
    if state.latitude and state.longitude and not state.timezone:
        state.timezone = lookup_timezone(state.latitude, state.longitude)

    save_wizard_state(session_id, state)
    return await step5_get(request)


@router.post("/step/4/timezone", response_class=HTMLResponse)
async def step4_timezone(request: Request) -> HTMLResponse:
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
        context={"timezone": tz, "timezones": _TIMEZONE_LIST},
    )


# ---------------------------------------------------------------------------
# Step 6: Provider Selection + Inline API Key Entry
# ---------------------------------------------------------------------------


@router.get("/step/6", response_class=HTMLResponse)
async def step6_get(request: Request) -> HTMLResponse:
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
            "step": 6,
            "state": state,
            "providers_by_domain": by_domain,
            "recommendations": recommendations,
            "error": None,
        },
    )


@router.get("/step/6/key-fields/{domain}/{provider_id}", response_class=HTMLResponse)
async def step6_key_fields(request: Request, domain: str, provider_id: str) -> HTMLResponse:
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


@router.post("/step/6/test-key/{provider_id}", response_class=HTMLResponse)
async def step6_test_key(request: Request, provider_id: str) -> HTMLResponse:
    """Test one provider's API key; return a result fragment."""
    session_id = _require_session(request)
    form = await request.form()
    info = get_provider(provider_id)

    if not info:
        return _render(
            request,
            "step_provider_test_result.html",
            {
                "test_result": {"success": False, "error": "This provider is not available. Please go back and choose a different provider."},
                "test_provider_id": provider_id,
                "test_provider_name": "Unknown provider",
            },
        )

    credentials: dict[str, str] = {}
    for field_name in info.auth_fields:
        credentials[field_name] = str(form.get(f"{provider_id}_{field_name}", "")).strip()

    # Pass station coordinates from wizard state so location-dependent providers
    # (IQAir, OpenWeatherMap AQI) use a real location instead of 0,0 (Gulf of Guinea).
    state = get_wizard_state(session_id)
    lat = state.latitude if state.latitude is not None else 0
    lon = state.longitude if state.longitude is not None else 0

    result = test_provider(info, credentials, latitude=lat, longitude=lon)
    return _render(
        request,
        "step_provider_test_result.html",
        {
            "test_result": result,
            "test_provider_id": provider_id,
            "test_provider_name": info.display_name,
        },
    )


@router.post("/step/6", response_class=HTMLResponse)
async def step6_post(request: Request) -> HTMLResponse:
    """Save provider selections and inline API keys, advance to step 7."""
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
    # Secret fields also send a "{provider_id}_{field_name}_unchanged" sentinel
    # when the user has not re-typed the key on re-render — keep the existing
    # stored value in that case rather than overwriting with an empty string.
    existing_api_keys = state.api_keys or {}
    api_keys: dict[str, dict[str, str]] = {}
    for provider_id in state.providers.values():
        info = get_provider(provider_id)
        if info and info.auth_fields:
            creds: dict[str, str] = {}
            for field_name in info.auth_fields:
                is_secret = "secret" in field_name or "password" in field_name or "key" in field_name
                submitted_value = str(form.get(f"{provider_id}_{field_name}", "")).strip()
                if submitted_value:
                    creds[field_name] = submitted_value
                elif is_secret:
                    # Check the sentinel: if unchanged=1 and field is empty, keep existing.
                    sentinel_name = f"{provider_id}_{field_name}_unchanged"
                    key_unchanged = str(form.get(sentinel_name, "0")).strip() == "1"
                    if key_unchanged:
                        existing_value = existing_api_keys.get(provider_id, {}).get(field_name, "")
                        if existing_value:
                            creds[field_name] = existing_value
                    # else: flag cleared and field empty — user intentionally cleared the key.
            if creds:
                api_keys[provider_id] = creds
    state.api_keys = api_keys

    save_wizard_state(session_id, state)
    return await step7_get(request)


# ---------------------------------------------------------------------------
# Step 7: Review + Apply
# ---------------------------------------------------------------------------


@router.get("/step/7", response_class=HTMLResponse)
async def step7_get(request: Request) -> HTMLResponse:
    session_id = _require_session(request)
    state = get_wizard_state(session_id)
    if state.db_host is None and state.station_name is None:
        _merge_from_existing_config(state)
    return _render(
        request,
        "step_review.html",
        {"step": 7, "state": state, "error": None},
    )


# Map wizard-internal provider IDs to the names expected by the API.
# The wizard stores user-facing identifiers (e.g. "nws_alerts") but the API
# schema uses shorter canonical names (e.g. "nws").  Add entries here as new
# providers are discovered to have a mismatch.
_PROVIDER_NAME_MAP: dict[str, str] = {
    "nws_alerts": "nws",
}


@router.post("/apply", response_class=HTMLResponse)
async def wizard_apply(request: Request) -> HTMLResponse:
    """Send config to the API, write local config files, display the completion page.

    Flow (ADR-038):
      1. Build the ApplyRequest payload from wizard state and POST it to the API.
         The API writes its own api.conf and secrets.env (DB password, provider
         API keys).  If this step fails, render the review page with the error so
         the operator can retry without re-entering all settings.
      2. Write local config files (realtime.conf, stack.conf, secrets.env with
         local secrets only — proxy secret and MQTT password).
      3. Clear wizard state and render the completion page.
    """
    session_id = _require_session(request)
    state = get_wizard_state(session_id)

    if _config_dir is None:
        assert _templates is not None
        return _templates.TemplateResponse(
            request=request,
            name="wizard/step_complete.html",
            context={
                "step": 7,
                "error": "The configuration directory has not been set. Please restart the setup tool with the correct --config-dir option.",
                "result": None,
            },
            status_code=500,
        )

    # ------------------------------------------------------------------
    # Step 1: Send configuration to the API (POST /setup/apply).
    # The API writes its own api.conf and stores DB password / provider keys
    # in its own secrets.env.  Fail early and show the review page on error.
    # ------------------------------------------------------------------

    # Build the column_mapping for the API: canonical → db_col (inverted from
    # state which stores db_col → canonical).  Skip unmapped columns (None value).
    api_column_mapping: dict[str, str] = {
        canonical: db_col
        for db_col, canonical in state.column_mapping.items()
        if canonical is not None
    }

    # Build providers dict: domain → ProviderConfig-shaped dict.
    # state.providers maps domain → provider_id.
    # state.api_keys maps provider_id → {field_name → value}.
    api_providers: dict[str, Any] = {}
    for domain, provider_id in state.providers.items():
        creds = state.api_keys.get(provider_id, {})
        # Normalise the provider name: the wizard may store an internal ID that
        # differs from the short name the API expects (e.g. "nws_alerts" → "nws").
        api_provider_name = _PROVIDER_NAME_MAP.get(provider_id, provider_id)
        provider_entry: dict[str, Any] = {"provider": api_provider_name}
        if creds.get("api_key"):
            provider_entry["api_key"] = creds["api_key"]
        if creds.get("api_secret"):
            provider_entry["api_secret"] = creds["api_secret"]
        if creds.get("pws_station_id"):
            provider_entry["pws_station_id"] = creds["pws_station_id"]
        if creds.get("nws_user_agent_contact"):
            provider_entry["nws_user_agent_contact"] = creds["nws_user_agent_contact"]
        if creds.get("iframe_url"):
            provider_entry["iframe_url"] = creds["iframe_url"]
        api_providers[domain] = provider_entry

    api_payload: dict[str, Any] = {
        "database": {
            "host": state.db_host or "",
            "port": state.db_port,
            "user": state.db_user or "",
            "password": state.db_password or "",
            "name": state.db_name,
        },
        "column_mapping": api_column_mapping,
        "station": {
            "name": state.station_name,
            "latitude": state.latitude,
            "longitude": state.longitude,
            "altitude_meters": state.altitude_meters,
            "timezone": state.timezone,
        },
    }

    if api_providers:
        api_payload["providers"] = api_providers

    if state.proxy_secret:
        api_payload["proxy_secret"] = state.proxy_secret

    try:
        client = _get_api_client(state)
        client.apply(api_payload)
    except ValueError:
        # API not connected — state.api_address or api_session_id is missing.
        return _render(
            request,
            "step_review.html",
            {
                "step": 7,
                "state": state,
                "error": "API not connected. Go back to step 1 and reconnect before applying.",
            },
            status_code=422,
        )
    except ApiClientError as exc:
        error_msg = _api_error_message(exc)
        logger.error("wizard_apply: API apply call failed (%s): %s", exc.status_code, exc.detail)
        return _render(
            request,
            "step_review.html",
            {
                "step": 7,
                "state": state,
                "error": f"Failed to apply API configuration: {error_msg}",
            },
            status_code=422,
        )
    except Exception:  # noqa: BLE001
        logger.exception("wizard_apply: unexpected error calling API apply")
        return _render(
            request,
            "step_review.html",
            {
                "step": 7,
                "state": state,
                "error": "Could not reach the API to apply configuration. Check that the API is running and try again.",
            },
            status_code=422,
        )

    # ------------------------------------------------------------------
    # Step 2: Write local config files (realtime.conf, stack.conf,
    # secrets.env with local secrets only).
    #
    # If this step fails, the API side is already done — its config was
    # consumed by the apply call above.  We return the *review page* (not
    # the completion page) so the operator can click Apply again after
    # fixing the permissions issue.  On retry the API may return 200
    # (idempotent) or 410 (already set up) — either way we can proceed to
    # the local write without re-doing the API call.
    # ------------------------------------------------------------------

    try:
        result = apply_wizard(state, _config_dir)
        clear_wizard_state(session_id)
    except OSError as exc:
        local_error = (
            f"API configuration saved successfully. "
            f"Local config write failed: {exc}. "
            f"Fix the permissions and click Apply again."
        )
        logger.error("apply_wizard OSError: %s", exc)
        return _render(
            request,
            "step_review.html",
            {"step": 7, "state": state, "error": local_error},
            status_code=422,
        )
    except Exception:  # noqa: BLE001
        local_error = (
            "API configuration saved successfully. "
            "Something went wrong writing the local config files — "
            "check the server log for details, fix the issue, and click Apply again."
        )
        logger.exception("apply_wizard unexpected error")
        return _render(
            request,
            "step_review.html",
            {"step": 7, "state": state, "error": local_error},
            status_code=422,
        )

    assert _templates is not None
    return _templates.TemplateResponse(
        request=request,
        name="wizard/step_complete.html",
        context={"step": 7, "error": None, "result": result},
        status_code=200,
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
    # Use the module-level comprehensive registry as the primary source.
    # Fall back to STOCK_COLUMN_MAP from the API package if loaded (adds any
    # newly promoted columns not yet reflected here), but the registry already
    # covers all canonical entities so the API import is supplementary only.
    valid_canonicals: set[str] = set(_ALL_CANONICAL_NAMES)
    try:
        from weewx_clearskies_api.db.reflection import STOCK_COLUMN_MAP  # type: ignore[import-untyped]
        valid_canonicals |= set(STOCK_COLUMN_MAP.values())
    except Exception:  # noqa: BLE001
        # API package unavailable — the module-level registry is sufficient.
        pass

    errors: dict[str, str] = {}

    # Duplicate-canonical check: build reverse map of canonical → [db_col, ...]
    seen: dict[str, list[str]] = {}
    for db_col, canonical in mapping.items():
        if canonical:
            seen.setdefault(canonical, []).append(db_col)
    for canonical, db_cols in seen.items():
        if len(db_cols) > 1:
            for db_col in db_cols:
                errors[db_col] = f'"{canonical}" is already used by another column — each column must have a unique name.'

    # Unknown canonical name check
    if valid_canonicals:
        for db_col, canonical in mapping.items():
            if canonical and canonical not in valid_canonicals and db_col not in errors:
                errors[db_col] = f'"{canonical}" is not a recognised weewx field name. Check the spelling or leave blank to skip this column.'

    return errors


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


# Note: CANONICAL_FIELD_GROUPS, canonical_groups, and _ALL_CANONICAL_NAMES
# are defined in wizard/schema.py and imported at the top of this module.
# _validate_column_mapping uses _ALL_CANONICAL_NAMES imported from schema.


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


def _existing_configs_present() -> bool:
    """Return True if realtime.conf or stack.conf exists in config_dir (wizard has run before).

    api.conf is written by the API itself (ADR-038) and is not a reliable sentinel.
    """
    if _config_dir is None:
        return False
    return (_config_dir / "realtime.conf").exists() or (_config_dir / "stack.conf").exists()


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
    if state.altitude_unit == "meters" and existing.altitude_unit != "meters":
        state.altitude_unit = existing.altitude_unit
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
        errors["mqtt_broker_host"] = "Please enter a broker hostname or IP address."
    if not (1 <= state.mqtt_broker_port <= 65535):
        errors["mqtt_broker_port"] = "Please enter a valid port number between 1 and 65535."
    if state.mqtt_qos not in (0, 1, 2):
        errors["mqtt_qos"] = "Quality of Service level must be 0, 1, or 2."
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
        return {"success": False, "error": "Please enter a broker hostname or IP address.", "note": None}

    # Resolve to all address families so IPv6 brokers work too.
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return {"success": False, "error": f"Could not find a broker at '{host}' — check that the hostname or IP address is correct.", "note": None}

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

    return {"success": False, "error": f"Could not connect to the broker at '{host}:{port}' — check that the host and port are correct and the broker is running.", "note": None}

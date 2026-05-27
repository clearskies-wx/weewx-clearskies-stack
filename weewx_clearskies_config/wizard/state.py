"""WizardState dataclass and in-memory session store.

The wizard collects configuration across 8 steps. Data accumulates in a
WizardState keyed by session ID. The store is backed by disk so progress
survives tool restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WizardState:
    """Accumulated configuration across all wizard steps."""

    # Step 1: API connection (ADR-038)
    api_address: str | None = None
    api_session_id: str | None = None
    cert_fingerprint: str | None = None

    # Database connection
    db_host: str | None = None
    db_port: int = 3306
    db_user: str | None = None
    db_password: str | None = None
    db_name: str = "weewx"

    # Column mapping — key=db_column_name, value=canonical_name or None (unmapped/skip)
    column_mapping: dict[str, str | None] = field(default_factory=dict)

    # Processed schema data cached between step 2 POST and step 3 GET.
    # Shape: {"stock_columns": [...], "unmapped_columns": [...], "total_columns": int, "stock_mapped": int}
    # Set by step 2 POST after calling ApiClient.get_schema(); cleared after step 3 advances.
    schema_data: dict[str, Any] | None = None

    # Station identity
    station_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_meters: float | None = None
    # Unit the operator used when entering altitude ("meters" or "feet").
    # Stored so the review page can display altitude in the same unit the user chose.
    altitude_unit: str = "meters"
    timezone: str | None = None

    # Provider selections — key=domain (forecast/alerts/aqi/earthquakes/radar), value=provider_id
    providers: dict[str, str] = field(default_factory=dict)

    # API keys — key=provider_id, value=dict of credential field names → values
    api_keys: dict[str, dict[str, str]] = field(default_factory=dict)

    # MQTT / data pipeline
    input_mode: str = "direct"  # "direct" or "mqtt"
    mqtt_broker_host: str = ""
    mqtt_broker_port: int = 1883
    mqtt_topic: str = "weewx/loop"
    mqtt_client_id: str = "weewx-clearskies-realtime"
    mqtt_username: str = ""
    # mqtt_password is never stored in progress JSON — only in secrets.env.
    mqtt_password: str = ""
    mqtt_tls: bool = False
    mqtt_qos: int = 0
    mqtt_keepalive: int = 60

    # Topology
    topology: str = "same-host"  # "same-host" or "cross-host"
    proxy_secret: str | None = None

    # Bind addresses
    api_bind_host: str = "127.0.0.1"
    api_bind_port: int = 8765
    realtime_bind_host: str = "127.0.0.1"
    realtime_bind_port: int = 8766

    # Navigation: True when step 3 (schema) was skipped due to all-stock columns.
    # Used by step 4 to render the correct Previous button target.
    schema_skipped: bool = False

    # Default locale for the dashboard UI (ADR-021).  One of the 13 supported
    # BCP-47 tags.  Sent to the API via POST /setup/apply and written to
    # [station] default_locale in api.conf by the API.
    default_locale: str = "en"

    # Webcam configuration
    webcam_enabled: bool = False
    webcam_image_url: str = "/webcam/weather_cam.jpg"
    webcam_video_url: str = "/webcam/weewx_timelapse.mp4"
    webcam_refresh_interval: int = 60

    # Step 0: skin.conf import — None means no import was attempted.
    # When populated, subsequent steps pre-fill from the imported data.
    imported_config: dict[str, Any] | None = None

    # Source skin name detected during step 0 import (e.g. "Belchertown").
    # Used by image resolution to locate files under /etc/weewx/skins/<skin>/.
    source_skin: str | None = None

    # Image resolution results from step 0 import (ADR-043).
    # Shape: {key: {"status": "local"|"api"|"unresolved"|"missing", "dest": str|None, "original": str}}
    # None means no image detection has been attempted.
    imported_images: dict[str, Any] | None = None

    # Unit configuration (step inserted after station identity).
    # Key = weewx unit group name (e.g. "group_temperature"),
    # Value = selected unit string (e.g. "degree_F").
    # None means the step has not been completed; defaults to US units on first visit.
    units: dict[str, str] | None = None

    # Branding (step 8)
    site_title: str = ""
    copyright_entity: str = ""
    logo_light_url: str = ""
    logo_dark_url: str = ""
    favicon_url: str = ""

    # Seismic config (inline in provider step, earthquakes domain)
    earthquake_radius_km: float = 100.0
    earthquake_min_magnitude: float = 2.0
    earthquake_default_days: int = 7


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

_store: dict[str, WizardState] = {}

# Set once at app startup via configure_state_persistence().
_config_dir: Path | None = None


def configure_state_persistence(config_dir: Path) -> None:
    """Register the config directory used for disk persistence.

    Called by create_wizard_router() so the module knows where to read/write
    progress files without having to thread config_dir through every call site.
    """
    global _config_dir  # noqa: PLW0603
    _config_dir = config_dir
    from weewx_clearskies_config.wizard.state_persistence import cleanup_stale_progress
    cleanup_stale_progress(config_dir)


def get_wizard_state(session_id: str) -> WizardState:
    """Return the WizardState for *session_id*.

    Lookup order:
      1. In-memory _store (fastest, already loaded this request).
      2. Disk progress file (survives restarts).
      3. Fresh WizardState (first visit).
    """
    if session_id in _store:
        return _store[session_id]
    if _config_dir is not None:
        from weewx_clearskies_config.wizard.state_persistence import load_progress
        loaded = load_progress(session_id, _config_dir)
        if loaded is not None:
            _store[session_id] = loaded
            return loaded
    _store[session_id] = WizardState()
    return _store[session_id]


def save_wizard_state(session_id: str, state: WizardState) -> None:
    """Persist *state* for *session_id* in memory and on disk."""
    _store[session_id] = state
    if _config_dir is not None:
        from weewx_clearskies_config.wizard.state_persistence import save_progress
        save_progress(session_id, state, _config_dir)


def clear_wizard_state(session_id: str) -> None:
    """Remove the WizardState for *session_id* (called after apply or cancel)."""
    _store.pop(session_id, None)
    if _config_dir is not None:
        from weewx_clearskies_config.wizard.state_persistence import delete_progress
        delete_progress(session_id, _config_dir)

"""WizardState dataclass and in-memory session store.

The wizard collects configuration across 8 steps. Data accumulates in a
WizardState keyed by session ID. The store is backed by disk so progress
survives tool restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WizardState:
    """Accumulated configuration across all wizard steps."""

    # Step 1: DB connection
    db_host: str | None = None
    db_port: int = 3306
    db_user: str | None = None
    db_password: str | None = None
    db_name: str = "weewx"

    # Step 2: Column mapping
    # key=db_column_name, value=canonical_name or None (unmapped/skip)
    column_mapping: dict[str, str | None] = field(default_factory=dict)

    # Step 3: Station identity
    station_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_meters: float | None = None
    timezone: str | None = None

    # Step 4: Provider selections
    # key=domain (forecast/alerts/aqi/earthquakes/radar), value=provider_id
    providers: dict[str, str] = field(default_factory=dict)

    # Step 5: API keys
    # key=provider_id, value=dict of credential field names → values
    api_keys: dict[str, dict[str, str]] = field(default_factory=dict)

    # Step 4: Data pipeline / MQTT
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

    # Step 6: Topology
    topology: str = "same-host"  # "same-host" or "cross-host"
    proxy_secret: str | None = None

    # Step 7: Bind addresses
    api_bind_host: str = "127.0.0.1"
    api_bind_port: int = 8765
    realtime_bind_host: str = "127.0.0.1"
    realtime_bind_port: int = 8766


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

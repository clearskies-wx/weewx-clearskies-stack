"""WizardState dataclass and in-memory session store.

The wizard collects configuration across 8 steps. Data accumulates in a
WizardState keyed by session ID. The store is in-memory (no persistence
across restarts), which is acceptable for a setup wizard that runs once.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


def get_wizard_state(session_id: str) -> WizardState:
    """Return the WizardState for *session_id*, creating one if absent."""
    if session_id not in _store:
        _store[session_id] = WizardState()
    return _store[session_id]


def save_wizard_state(session_id: str, state: WizardState) -> None:
    """Persist *state* for *session_id*."""
    _store[session_id] = state


def clear_wizard_state(session_id: str) -> None:
    """Remove the WizardState for *session_id* (called after apply or cancel)."""
    _store.pop(session_id, None)

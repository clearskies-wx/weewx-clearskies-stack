"""Tests for weewx_clearskies_config.wizard.state — WizardState and session store."""

from __future__ import annotations

import pytest

from weewx_clearskies_config.wizard.state import (
    WizardState,
    clear_wizard_state,
    get_wizard_state,
    save_wizard_state,
)


# ---------------------------------------------------------------------------
# Helpers — isolate global _store between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_store():
    """Clear module-level _store before and after each test for isolation."""
    import weewx_clearskies_config.wizard.state as state_module
    state_module._store.clear()
    yield
    state_module._store.clear()


# ---------------------------------------------------------------------------
# WizardState defaults
# ---------------------------------------------------------------------------


def test_wizard_state_has_expected_default_db_port():
    state = WizardState()
    assert state.db_port == 3306


def test_wizard_state_has_expected_default_db_name():
    state = WizardState()
    assert state.db_name == "weewx"


def test_wizard_state_has_expected_default_topology():
    state = WizardState()
    assert state.topology == "same-host"


def test_wizard_state_has_expected_default_api_bind_host():
    state = WizardState()
    assert state.api_bind_host == "127.0.0.1"


def test_wizard_state_column_mapping_defaults_to_empty_dict():
    state = WizardState()
    assert state.column_mapping == {}


def test_wizard_state_providers_defaults_to_empty_dict():
    state = WizardState()
    assert state.providers == {}


def test_wizard_state_api_keys_defaults_to_empty_dict():
    state = WizardState()
    assert state.api_keys == {}


# ---------------------------------------------------------------------------
# get_wizard_state — creates missing state
# ---------------------------------------------------------------------------


def test_get_wizard_state_creates_new_state_for_unknown_session():
    state = get_wizard_state("sess-new")
    assert isinstance(state, WizardState)


def test_get_wizard_state_returns_same_instance_on_repeated_calls():
    s1 = get_wizard_state("sess-same")
    s2 = get_wizard_state("sess-same")
    assert s1 is s2


def test_get_wizard_state_different_sessions_are_independent():
    s1 = get_wizard_state("sess-a")
    s2 = get_wizard_state("sess-b")
    s1.db_host = "host-a"
    assert s2.db_host is None


# ---------------------------------------------------------------------------
# save_wizard_state
# ---------------------------------------------------------------------------


def test_save_wizard_state_persists_changes():
    state = WizardState(db_host="192.168.1.1")
    save_wizard_state("sess-save", state)
    retrieved = get_wizard_state("sess-save")
    assert retrieved.db_host == "192.168.1.1"


def test_save_wizard_state_replaces_existing_state():
    original = WizardState(db_host="original-host")
    save_wizard_state("sess-replace", original)

    updated = WizardState(db_host="updated-host")
    save_wizard_state("sess-replace", updated)

    retrieved = get_wizard_state("sess-replace")
    assert retrieved.db_host == "updated-host"


# ---------------------------------------------------------------------------
# clear_wizard_state
# ---------------------------------------------------------------------------


def test_clear_wizard_state_removes_state():
    get_wizard_state("sess-clear")  # ensure it exists
    clear_wizard_state("sess-clear")
    # After clearing, get_wizard_state should create a fresh one
    fresh = get_wizard_state("sess-clear")
    assert fresh.db_host is None


def test_clear_wizard_state_nonexistent_session_does_not_raise():
    # Must not raise KeyError for unknown session
    clear_wizard_state("sess-never-existed")


def test_clear_wizard_state_does_not_affect_other_sessions():
    get_wizard_state("sess-keep")
    save_wizard_state("sess-keep", WizardState(db_host="keep-me"))
    get_wizard_state("sess-remove")
    clear_wizard_state("sess-remove")
    # The kept session must survive
    assert get_wizard_state("sess-keep").db_host == "keep-me"


# ---------------------------------------------------------------------------
# Earthquake config fields — defaults and persistence
# ---------------------------------------------------------------------------


def test_wizard_state_earthquake_radius_km_defaults_to_100():
    state = WizardState()
    assert state.earthquake_radius_km == 100.0


def test_wizard_state_earthquake_min_magnitude_defaults_to_2():
    state = WizardState()
    assert state.earthquake_min_magnitude == 2.0


def test_wizard_state_earthquake_default_days_defaults_to_7():
    state = WizardState()
    assert state.earthquake_default_days == 7


def test_wizard_state_earthquake_fields_can_be_overridden():
    state = WizardState(
        earthquake_radius_km=250.0,
        earthquake_min_magnitude=3.5,
        earthquake_default_days=14,
    )
    assert state.earthquake_radius_km == 250.0
    assert state.earthquake_min_magnitude == 3.5
    assert state.earthquake_default_days == 14


def test_wizard_state_earthquake_fields_persist_across_save_get():
    state = WizardState(
        earthquake_radius_km=500.0,
        earthquake_min_magnitude=4.0,
        earthquake_default_days=30,
    )
    save_wizard_state("sess-eq", state)
    retrieved = get_wizard_state("sess-eq")
    assert retrieved.earthquake_radius_km == 500.0
    assert retrieved.earthquake_min_magnitude == 4.0
    assert retrieved.earthquake_default_days == 30

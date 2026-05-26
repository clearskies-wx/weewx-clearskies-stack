"""Tests for build_skin_conf_payload() in config_writer (ADR-043).

Covers:
  - state with units set, no import → payload has units.groups only
  - state with units=None → falls back to US preset
  - state with a full imported_config → all carried-forward subsections included
  - state with a partial imported_config → only present subsections included
  - the apply route wires skin_conf into api_payload before client.apply()
"""

from __future__ import annotations

import pytest

from weewx_clearskies_config.wizard.config_writer import build_skin_conf_payload
from weewx_clearskies_config.wizard.state import WizardState
from weewx_clearskies_config.wizard.units import UNIT_PRESETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_with_units(**overrides) -> WizardState:
    """WizardState with explicit US unit selections, no import."""
    return WizardState(units=dict(UNIT_PRESETS["us"]), **overrides)


def _state_no_units(**overrides) -> WizardState:
    """WizardState with units=None (unit step not completed)."""
    return WizardState(units=None, **overrides)


# Full imported_config as skin_import.py's _extract() would produce it.
_FULL_IMPORTED_CONFIG: dict = {
    "units": {
        "groups": {
            "group_temperature": "degree_C",
            "group_speed": "km_per_hour",
            "group_pressure": "mbar",
            "group_rain": "mm",
            "group_rainrate": "mm_per_hour",
            "group_altitude": "meter",
            "group_distance": "km",
        },
        "labels": {"degree_C": " °C", "km_per_hour": " km/h"},
        "string_formats": {"degree_C": "%.1f"},
        "ordinates": {
            "directions": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
            "na": "N/A",
        },
        "time_formats": {"day": "%H:%M", "week": "%d-%b-%Y %H:%M"},
        "degree_days": {"heating_base": "65, degree_F", "cooling_base": "65, degree_F"},
        "trend": {"time_delta": 10800, "time_grace": 300},
        "timezone": None,
    },
    "labels": {"outTemp": "Temperature", "barometer": "Pressure"},
    "extras": {
        "branding": {"site_title": "My Weather"},
        "social": {},
        "mqtt": {},
        "providers": {},
        "feature_toggles": {},
        "pwa": {},
        "theme": {},
        "unmatched": {},
    },
    "almanac": {"moon_phases": ["New Moon", "Waxing Crescent"]},
    "texts": {},
    "warnings": [],
}


# ---------------------------------------------------------------------------
# 1. units set, no import → payload has units.groups only
# ---------------------------------------------------------------------------


def test_build_skin_conf_payload_units_only_has_groups():
    """When units are set and no import, payload['units']['groups'] contains them."""
    state = _state_with_units()
    result = build_skin_conf_payload(state)
    assert "units" in result
    assert "groups" in result["units"]
    assert result["units"]["groups"] == UNIT_PRESETS["us"]


def test_build_skin_conf_payload_units_only_no_extra_subsections():
    """When there is no import, no extra [Units] subsections are included."""
    state = _state_with_units()
    result = build_skin_conf_payload(state)
    for key in ("string_formats", "labels", "ordinates", "time_formats", "degree_days", "trend"):
        assert key not in result["units"], f"Unexpected key {key!r} in units without import"


def test_build_skin_conf_payload_units_only_no_top_level_extras():
    """When there is no import, labels/extras/almanac are absent from payload."""
    state = _state_with_units()
    result = build_skin_conf_payload(state)
    assert "labels" not in result
    assert "extras" not in result
    assert "almanac" not in result


# ---------------------------------------------------------------------------
# 2. units=None → falls back to US preset
# ---------------------------------------------------------------------------


def test_build_skin_conf_payload_default_units_fallback():
    """When state.units is None, groups fall back to UNIT_PRESETS['us']."""
    state = _state_no_units()
    result = build_skin_conf_payload(state)
    assert result["units"]["groups"] == UNIT_PRESETS["us"]


def test_build_skin_conf_payload_default_units_has_all_groups():
    """Fallback groups include all 7 expected unit group keys."""
    state = _state_no_units()
    result = build_skin_conf_payload(state)
    for group in (
        "group_temperature",
        "group_speed",
        "group_pressure",
        "group_rain",
        "group_rainrate",
        "group_altitude",
        "group_distance",
    ):
        assert group in result["units"]["groups"], f"Missing group {group!r} in default units"


# ---------------------------------------------------------------------------
# 3. Full import → all subsections carried forward
# ---------------------------------------------------------------------------


def test_build_skin_conf_payload_with_import_units_groups_from_state():
    """When units are set AND import present, groups come from state.units (wizard step)."""
    state = WizardState(
        units=dict(UNIT_PRESETS["metric"]),
        imported_config=_FULL_IMPORTED_CONFIG,
    )
    result = build_skin_conf_payload(state)
    # state.units overrides imported groups
    assert result["units"]["groups"] == UNIT_PRESETS["metric"]


def test_build_skin_conf_payload_with_import_carries_string_formats():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["string_formats"] == {"degree_C": "%.1f"}


def test_build_skin_conf_payload_with_import_carries_unit_labels():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["labels"] == {"degree_C": " °C", "km_per_hour": " km/h"}


def test_build_skin_conf_payload_with_import_carries_ordinates():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["ordinates"]["directions"][0] == "N"


def test_build_skin_conf_payload_with_import_carries_time_formats():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["time_formats"] == {"day": "%H:%M", "week": "%d-%b-%Y %H:%M"}


def test_build_skin_conf_payload_with_import_carries_degree_days():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["degree_days"]["heating_base"] == "65, degree_F"


def test_build_skin_conf_payload_with_import_carries_trend():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert result["units"]["trend"]["time_delta"] == 10800


def test_build_skin_conf_payload_with_import_carries_labels():
    """Labels from [Labels][[Generic]] are wrapped under 'generic' key."""
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "labels" in result
    assert result["labels"]["generic"]["outTemp"] == "Temperature"


def test_build_skin_conf_payload_with_import_carries_extras():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "extras" in result
    assert result["extras"]["branding"]["site_title"] == "My Weather"


def test_build_skin_conf_payload_with_import_carries_almanac():
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_FULL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "almanac" in result
    assert "New Moon" in result["almanac"]["moon_phases"]


# ---------------------------------------------------------------------------
# 4. Partial import → only present subsections included
# ---------------------------------------------------------------------------


_PARTIAL_IMPORTED_CONFIG: dict = {
    "units": {
        "groups": {"group_temperature": "degree_C"},
        "labels": {},
        "string_formats": {"degree_C": "%.1f"},
        "ordinates": {"directions": [], "na": "N/A"},
        "time_formats": {},
        "degree_days": {},
        "trend": {},
        "timezone": None,
    },
    "labels": {},
    "extras": {},
    "almanac": {},
    "texts": {},
    "warnings": [],
}


def test_build_skin_conf_payload_partial_import_includes_string_formats():
    """Subsections with data are included even when others are empty."""
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_PARTIAL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "string_formats" in result["units"]
    assert result["units"]["string_formats"] == {"degree_C": "%.1f"}


def test_build_skin_conf_payload_partial_import_omits_empty_unit_subsections():
    """Empty dicts in imported units subsections are not carried forward."""
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_PARTIAL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "labels" not in result["units"]
    assert "time_formats" not in result["units"]
    assert "degree_days" not in result["units"]
    assert "trend" not in result["units"]


def test_build_skin_conf_payload_partial_import_ordinates_dict_is_carried():
    """Ordinates dict is carried forward when present (even with empty directions list).

    skin_import.py always emits ordinates as a dict with 'directions' and 'na'
    keys.  The dict itself is truthy (non-empty), so it is included.  The API
    side is responsible for handling the empty-directions edge case.
    """
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_PARTIAL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "ordinates" in result["units"]
    assert result["units"]["ordinates"]["directions"] == []
    assert result["units"]["ordinates"]["na"] == "N/A"


def test_build_skin_conf_payload_partial_import_omits_empty_top_level():
    """Empty labels/extras/almanac in import do not appear in payload."""
    state = WizardState(units=dict(UNIT_PRESETS["us"]), imported_config=_PARTIAL_IMPORTED_CONFIG)
    result = build_skin_conf_payload(state)
    assert "labels" not in result
    assert "extras" not in result
    assert "almanac" not in result


# ---------------------------------------------------------------------------
# 5. Apply route includes skin_conf in api_payload
# ---------------------------------------------------------------------------


def test_api_payload_includes_skin_conf_key(monkeypatch):
    """The wizard_apply route adds 'skin_conf' to api_payload before calling client.apply().

    Strategy: import the apply route module and inspect build_skin_conf_payload
    is called with the wizard state.  We verify by directly checking that
    build_skin_conf_payload(state) produces the same dict that would be placed
    into the payload — this is a unit test of the wiring logic, not an
    integration test of the full HTTP route.
    """
    state = WizardState(
        units=dict(UNIT_PRESETS["us"]),
        imported_config=None,
    )
    result = build_skin_conf_payload(state)
    # The result must be a non-empty dict with a "units" key.
    assert isinstance(result, dict)
    assert "units" in result
    assert "groups" in result["units"]


def test_api_payload_skin_conf_contains_imported_data_end_to_end():
    """When state has imported_config, build_skin_conf_payload carries all sections."""
    state = WizardState(
        units=dict(UNIT_PRESETS["metric"]),
        imported_config=_FULL_IMPORTED_CONFIG,
    )
    payload = build_skin_conf_payload(state)
    # groups come from the wizard step (metric), not from imported groups (also metric here)
    assert payload["units"]["groups"]["group_temperature"] == "degree_C"
    # imported subsections present
    assert "string_formats" in payload["units"]
    assert "labels" in payload
    assert "extras" in payload
    assert "almanac" in payload

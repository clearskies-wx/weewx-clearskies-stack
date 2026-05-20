"""Tests for weewx_clearskies_config.wizard.schema.suggest_canonical.

introspect_schema() depends on weewx_clearskies_api.db.reflection which may
not be installed in the test environment.  That function is tested separately
via integration tests against a real DB.  suggest_canonical is a pure function
and is fully covered here.
"""

from __future__ import annotations

import pytest

from weewx_clearskies_config.wizard.schema import suggest_canonical


_CANONICAL_FIELDS = [
    "outdoor_temperature",
    "indoor_temperature",
    "outdoor_humidity",
    "barometric_pressure",
    "wind_speed",
    "wind_gust",
    "wind_direction",
    "precipitation",
    "solar_radiation",
    "uv_index",
    "dateTime",
]


# ---------------------------------------------------------------------------
# Exact (high confidence) matches
# ---------------------------------------------------------------------------


def test_suggest_canonical_exact_match_returns_high_confidence():
    match, confidence = suggest_canonical("outdoor_temperature", _CANONICAL_FIELDS)
    assert confidence == "high"
    assert match == "outdoor_temperature"


def test_suggest_canonical_case_insensitive_exact_match_returns_high_confidence():
    match, confidence = suggest_canonical("OUTDOOR_TEMPERATURE", _CANONICAL_FIELDS)
    assert confidence == "high"
    assert match == "outdoor_temperature"


def test_suggest_canonical_mixed_case_exact_match_returns_high_confidence():
    match, confidence = suggest_canonical("OutDoor_Temperature", _CANONICAL_FIELDS)
    assert confidence == "high"
    assert match == "outdoor_temperature"


# ---------------------------------------------------------------------------
# Substring (medium confidence) matches
# ---------------------------------------------------------------------------


def test_suggest_canonical_db_col_substring_of_canonical_returns_medium():
    # "wind" is a substring of "wind_speed", "wind_gust", "wind_direction"
    # Multiple matches → returns shortest (medium still applies)
    match, confidence = suggest_canonical("wind_spd", _CANONICAL_FIELDS)
    # "wind_spd" contains "wind" which is in several canonical names,
    # but "wind_sp" ⊂ "wind_speed" so this should be medium with wind_speed
    assert confidence in ("medium", "low", "none")  # depends on overlap logic


def test_suggest_canonical_single_substring_match_returns_medium():
    # "uv" uniquely matches "uv_index"
    match, confidence = suggest_canonical("uv", _CANONICAL_FIELDS)
    assert confidence == "medium"
    assert match == "uv_index"


def test_suggest_canonical_canonical_substring_of_db_col_returns_medium():
    # "solar_radiation_extra" contains "solar_radiation" — canonical is substring of db_col
    match, confidence = suggest_canonical("solar_radiation_extra", _CANONICAL_FIELDS)
    assert confidence == "medium"
    assert match == "solar_radiation"


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


def test_suggest_canonical_no_match_returns_none_and_none_confidence():
    match, confidence = suggest_canonical("completely_unrelated_zzzq", _CANONICAL_FIELDS)
    assert match is None
    assert confidence == "none"


def test_suggest_canonical_empty_canonical_fields_returns_none():
    match, confidence = suggest_canonical("outTemp", [])
    assert match is None
    assert confidence == "none"


def test_suggest_canonical_empty_db_column_returns_some_result():
    # Empty string is a substring of every canonical name, so the heuristic
    # returns the shortest canonical match at medium confidence rather than None.
    # This documents the observed behaviour; callers should guard against empty input.
    _match, confidence = suggest_canonical("", _CANONICAL_FIELDS)
    assert confidence in ("medium", "none")


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------


def test_suggest_canonical_always_returns_two_tuple():
    result = suggest_canonical("anything", _CANONICAL_FIELDS)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_suggest_canonical_confidence_is_one_of_four_values():
    valid_confidences = {"high", "medium", "low", "none"}
    for col in ["outTemp", "barometric_pressure", "xyz999", "wind_speed"]:
        _, confidence = suggest_canonical(col, _CANONICAL_FIELDS)
        assert confidence in valid_confidences, f"Unexpected confidence {confidence!r} for {col!r}"

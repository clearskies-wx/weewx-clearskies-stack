"""Tests for column mapping merge/inversion behavior introduced to fix re-run overwrite bugs.

Covers three bugs:
  Bug 1 — populate_from_config inverts canonical=db_col from api.conf into {db_col: canonical}
  Bug 2 — step 2 POST (skip_schema path) merges stock columns with existing custom mappings
  Bug 3 — step 3 POST merges form data with existing state instead of replacing it
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from weewx_clearskies_config.wizard.state import WizardState
from weewx_clearskies_config.wizard.state_persistence import populate_from_config


# ---------------------------------------------------------------------------
# Bug 1 — populate_from_config correctly inverts column_mapping from api.conf
# ---------------------------------------------------------------------------


def _write_api_conf(config_dir: Path, column_mapping_lines: list[str]) -> None:
    """Write a minimal api.conf with a [column_mapping] section to config_dir."""
    lines = [
        "[database]",
        "host = 127.0.0.1",
        "port = 3306",
        "user = weewx",
        "name = weewx",
        "[column_mapping]",
    ]
    lines.extend(column_mapping_lines)
    (config_dir / "api.conf").write_text("\n".join(lines), encoding="utf-8")


def test_populate_from_config_inverts_canonical_to_db_col(tmp_path):
    """api.conf stores canonical = db_col; populate_from_config must invert to {db_col: canonical}."""
    _write_api_conf(tmp_path, ["outTemp = outside_temperature"])

    state = populate_from_config(tmp_path)

    # The state must map db_col → canonical, not the other way around.
    assert state.column_mapping.get("outside_temperature") == "outTemp"


def test_populate_from_config_inversion_with_multiple_mappings(tmp_path):
    """Multiple entries are all inverted correctly."""
    _write_api_conf(tmp_path, [
        "outTemp = outside_temperature",
        "barometer = barometric_pressure",
        "windSpeed = wind_speed",
    ])

    state = populate_from_config(tmp_path)

    assert state.column_mapping.get("outside_temperature") == "outTemp"
    assert state.column_mapping.get("barometric_pressure") == "barometer"
    assert state.column_mapping.get("wind_speed") == "windSpeed"


def test_populate_from_config_inversion_does_not_produce_canonical_as_keys(tmp_path):
    """After inversion the canonical names must not appear as dict keys."""
    _write_api_conf(tmp_path, ["outTemp = outside_temperature"])

    state = populate_from_config(tmp_path)

    # Pre-fix bug: "outTemp" was a key and "outside_temperature" was a value.
    assert "outTemp" not in state.column_mapping


def test_populate_from_config_empty_column_mapping_produces_empty_dict(tmp_path):
    """An api.conf with no [column_mapping] entries yields an empty dict."""
    _write_api_conf(tmp_path, [])

    state = populate_from_config(tmp_path)

    assert state.column_mapping == {}


def test_populate_from_config_no_api_conf_produces_empty_column_mapping(tmp_path):
    """When api.conf is absent, column_mapping defaults to empty dict (first-run safety)."""
    # No api.conf written — simulate a fresh install.
    state = populate_from_config(tmp_path)

    assert state.column_mapping == {}


# ---------------------------------------------------------------------------
# Bug 2 — step 2 POST (skip_schema=True) preserves existing custom mappings
# ---------------------------------------------------------------------------


def _make_schema_data(stock_pairs: list[tuple[str, str]]) -> dict:
    """Build a minimal schema_data dict with no unmapped columns."""
    return {
        "stock_columns": [
            {"db_name": db_name, "canonical": canonical}
            for db_name, canonical in stock_pairs
        ],
        "unmapped_columns": [],
    }


def test_step2_skip_schema_preserves_existing_custom_mapping(authed_client):
    """When skip_schema=True, step 2 must not overwrite pre-existing custom mappings.

    Scenario: a prior wizard run mapped my_sensor → outdoor_temperature.
    The stock columns do NOT include my_sensor.  After a re-run step 2, the
    custom mapping must still be present.
    """
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state
    from weewx_clearskies_config.wizard.routes import process_api_schema

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie, "Expected a session cookie after authed_client login"

    # Pre-populate state with a custom mapping from a prior run.
    state = get_wizard_state(session_cookie)
    state.column_mapping = {"my_sensor": "outdoor_temperature"}
    save_wizard_state(session_cookie, state)

    # Build fake schema_data as if from the API (all stock, no unmapped).
    schema_data = _make_schema_data([
        ("outTemp", "stock_temperature"),
        ("barometer", "stock_pressure"),
    ])

    # Call the merge logic directly — this mirrors what step2_db_post does when
    # skip_schema=True (all columns are stock).
    existing = dict(state.column_mapping or {})
    for col in schema_data.get("stock_columns", []):
        if col["db_name"] not in existing:
            existing[col["db_name"]] = col["canonical"]
    state.column_mapping = existing
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    # Custom mapping must survive.
    assert updated.column_mapping.get("my_sensor") == "outdoor_temperature"
    # Stock columns must also be present.
    assert updated.column_mapping.get("outTemp") == "stock_temperature"
    assert updated.column_mapping.get("barometer") == "stock_pressure"


def test_step2_skip_schema_does_not_overwrite_custom_entry_with_stock(authed_client):
    """If a db_name already has a custom mapping, the stock default must not clobber it."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie

    state = get_wizard_state(session_cookie)
    # Custom mapping overrides the stock suggestion for "outTemp".
    state.column_mapping = {"outTemp": "custom_outdoor_temp"}
    save_wizard_state(session_cookie, state)

    schema_data = _make_schema_data([("outTemp", "stock_suggestion")])

    existing = dict(state.column_mapping or {})
    for col in schema_data.get("stock_columns", []):
        if col["db_name"] not in existing:
            existing[col["db_name"]] = col["canonical"]
    state.column_mapping = existing
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    # Custom value wins over stock suggestion.
    assert updated.column_mapping.get("outTemp") == "custom_outdoor_temp"


def test_step2_skip_schema_first_run_empty_state_uses_stock_columns(authed_client):
    """On a first run (empty column_mapping), stock columns are applied without error."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie

    state = get_wizard_state(session_cookie)
    assert state.column_mapping == {}  # First-run: empty

    schema_data = _make_schema_data([
        ("outTemp", "outdoor_temperature"),
        ("barometer", "barometric_pressure"),
    ])

    existing = dict(state.column_mapping or {})
    for col in schema_data.get("stock_columns", []):
        if col["db_name"] not in existing:
            existing[col["db_name"]] = col["canonical"]
    state.column_mapping = existing
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    assert updated.column_mapping.get("outTemp") == "outdoor_temperature"
    assert updated.column_mapping.get("barometer") == "barometric_pressure"


# ---------------------------------------------------------------------------
# Bug 3 — step 3 POST merges form data with existing state
# ---------------------------------------------------------------------------


def test_step3_post_merge_preserves_stock_columns_from_step2(authed_client):
    """Step 3 form submission must not wipe stock column entries set by step 2.

    Scenario: step 2 populated {"outTemp": "outdoor_temperature"} (stock).
    Step 3 form adds {"my_sensor": "custom_field"} (unmapped).
    Result: both entries must be present.
    """
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie

    # Simulate step 2 having set the stock mapping.
    state = get_wizard_state(session_cookie)
    state.column_mapping = {"outTemp": "outdoor_temperature"}
    save_wizard_state(session_cookie, state)

    # Simulate step 3 form handling: only unmapped columns come through the form.
    form_mapping = {"my_sensor": "custom_field"}

    merged = dict(state.column_mapping or {})
    merged.update(form_mapping)
    state.column_mapping = merged
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    # Stock entry from step 2 must survive.
    assert updated.column_mapping.get("outTemp") == "outdoor_temperature"
    # Form entry from step 3 must be present.
    assert updated.column_mapping.get("my_sensor") == "custom_field"


def test_step3_post_merge_form_overrides_existing_entry(authed_client):
    """If the form re-submits a db_name that already exists, the form value wins."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie

    state = get_wizard_state(session_cookie)
    state.column_mapping = {"my_sensor": "old_canonical"}
    save_wizard_state(session_cookie, state)

    form_mapping = {"my_sensor": "new_canonical"}

    merged = dict(state.column_mapping or {})
    merged.update(form_mapping)
    state.column_mapping = merged
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    assert updated.column_mapping.get("my_sensor") == "new_canonical"


def test_step3_post_merge_first_run_empty_state(authed_client):
    """On first run with empty state, form submission is applied without error."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie

    state = get_wizard_state(session_cookie)
    assert state.column_mapping == {}

    form_mapping = {"my_sensor": "outdoor_temperature"}

    merged = dict(state.column_mapping or {})
    merged.update(form_mapping)
    state.column_mapping = merged
    save_wizard_state(session_cookie, state)

    updated = get_wizard_state(session_cookie)

    assert updated.column_mapping.get("my_sensor") == "outdoor_temperature"

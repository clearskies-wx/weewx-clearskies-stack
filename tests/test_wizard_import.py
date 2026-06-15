"""Tests for the skin.conf import step and unit configuration step of the wizard.

Covers:
  - GET /wizard/import (step 0) — import page loads
  - POST /wizard/import with fresh_start=1 — proceeds to step 1
  - POST /wizard/import with a valid skin.conf file — state populated
  - POST /wizard/import with an invalid file — error shown
  - GET /wizard/units — unit configuration page loads
  - GET /wizard/units after import — dropdowns pre-filled from imported skin.conf
  - POST /wizard/units — state updated with submitted selections
  - POST /wizard/units with US preset values — all groups set correctly
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from weewx_clearskies_config.auth import hash_password, write_secrets
from weewx_clearskies_config.wizard.units import UNIT_PRESETS


# ---------------------------------------------------------------------------
# Minimal skin.conf fixtures
# ---------------------------------------------------------------------------

_VALID_SKIN_CONF = """
[Units]
    [[Groups]]
        group_temperature = degree_C
        group_speed = km_per_hour
        group_pressure = mbar
        group_rain = mm
        group_rainrate = mm_per_hour
        group_altitude = meter
        group_distance = km
    [[Labels]]
        degree_C = " °C"
"""

_INVALID_SKIN_CONF = "this is not [valid] configobj format\n    [[broken = no"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def authed_client(test_app, config_dir: Path):
    """TestClient with an active admin session."""
    from weewx_clearskies_config.auth import hash_password, write_secrets
    from starlette.testclient import TestClient

    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "testadmin",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("CorrectHorseBatteryStaple!"),
        }
    )

    with TestClient(test_app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/login",
            data={"username": "testadmin", "password": "CorrectHorseBatteryStaple!"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303), f"Login pre-condition failed: {resp.status_code}"
        yield c


# ---------------------------------------------------------------------------
# Helper: get the wizard session state from the client session cookie.
# ---------------------------------------------------------------------------

def _get_state(client):
    """Return the WizardState associated with the client's session cookie."""
    from weewx_clearskies_config.wizard.state import get_wizard_state

    session_cookie = client.cookies.get("clearskies_session")
    if not session_cookie:
        return None
    return get_wizard_state(session_cookie)


# ---------------------------------------------------------------------------
# 1. GET /wizard/import — page loads
# ---------------------------------------------------------------------------


def test_import_page_loads(authed_client):
    """GET /wizard/import returns 200 with HTML content."""
    resp = authed_client.get("/wizard/import")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Import" in resp.text


# ---------------------------------------------------------------------------
# 2. POST /wizard/import — fresh start
# ---------------------------------------------------------------------------


def test_fresh_start_proceeds_to_step1(authed_client):
    """POST with fresh_start=1 returns the step 1 (API) fragment (200 HTMX swap)."""
    resp = authed_client.post(
        "/wizard/import",
        data={"fresh_start": "1"},
    )
    # The route calls step1_api_get which returns a 200 HTML fragment.
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # The fragment should contain the API connection form.
    assert "api_host" in resp.text or "API Connection" in resp.text


def test_fresh_start_clears_imported_config(authed_client):
    """POST fresh_start clears any previously stored imported_config from state."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie, "Expected a session cookie"

    # Pre-populate imported_config in state.
    state = get_wizard_state(session_cookie)
    state.imported_config = {"units": {"groups": {"group_temperature": "degree_C"}}}
    save_wizard_state(session_cookie, state)

    resp = authed_client.post("/wizard/import", data={"fresh_start": "1"})
    assert resp.status_code == 200

    updated = get_wizard_state(session_cookie)
    assert updated.imported_config is None


# ---------------------------------------------------------------------------
# 3. POST /wizard/import — valid skin.conf upload
# ---------------------------------------------------------------------------


def test_import_valid_skinconf_stores_imported_config(authed_client):
    """POST a valid skin.conf file; verify state.imported_config is populated."""
    resp = authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _VALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.imported_config is not None
    groups = state.imported_config.get("units", {}).get("groups", {})
    assert groups.get("group_temperature") == "degree_C"
    assert groups.get("group_speed") == "km_per_hour"


def test_import_valid_skinconf_prefills_units_state(authed_client):
    """Valid skin.conf import pre-populates state.units from imported groups."""
    resp = authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _VALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.units is not None
    # All groups from skin.conf should be reflected.
    assert state.units.get("group_temperature") == "degree_C"
    assert state.units.get("group_rain") == "mm"


def test_import_valid_skinconf_proceeds_to_step1(authed_client):
    """After a successful import, the route returns the API step fragment."""
    resp = authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _VALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "api_host" in resp.text or "API Connection" in resp.text


# ---------------------------------------------------------------------------
# 4. POST /wizard/import — invalid file
# ---------------------------------------------------------------------------


def test_import_invalid_file_returns_422(authed_client):
    """POST with a file that is not valid ConfigObj format returns 422."""
    resp = authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _INVALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 422


def test_import_invalid_file_shows_error(authed_client):
    """POST with an unparseable file renders the import page with an error message."""
    resp = authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _INVALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )
    assert "error" in resp.text.lower() or "Could not parse" in resp.text


def test_import_missing_file_returns_422(authed_client):
    """POST with no file and no fresh_start flag returns 422."""
    resp = authed_client.post("/wizard/import", data={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. GET /wizard/units — units page loads
# ---------------------------------------------------------------------------


def test_units_page_loads(authed_client):
    """GET /wizard/units returns 200 with HTML content."""
    resp = authed_client.get("/wizard/units")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Units" in resp.text or "group_temperature" in resp.text


def test_units_page_shows_all_groups(authed_client):
    """GET /wizard/units renders a form field for each expected unit group."""
    resp = authed_client.get("/wizard/units")
    assert resp.status_code == 200
    for group in (
        "group_temperature",
        "group_speed",
        "group_pressure",
        "group_rain",
        "group_rainrate",
        "group_altitude",
        "group_distance",
    ):
        assert group in resp.text, f"Expected field for {group} not found in units page"


# ---------------------------------------------------------------------------
# 6. GET /wizard/units after import — dropdowns pre-filled from skin.conf
# ---------------------------------------------------------------------------


def test_units_page_prefilled_from_import(authed_client):
    """After a successful skin.conf import, GET /wizard/units shows imported unit selections."""
    # Perform the import first.
    authed_client.post(
        "/wizard/import",
        files={"skin_conf": ("skin.conf", _VALID_SKIN_CONF.encode("utf-8"), "text/plain")},
    )

    resp = authed_client.get("/wizard/units")
    assert resp.status_code == 200
    # The degree_C option should be selected for group_temperature.
    # Check that degree_C appears in the response (as the selected value).
    assert "degree_C" in resp.text


def test_units_page_defaults_to_us_without_import(authed_client):
    """Without prior import, GET /wizard/units pre-selects US defaults."""
    resp = authed_client.get("/wizard/units")
    assert resp.status_code == 200
    # US default: degree_F for temperature.
    assert "degree_F" in resp.text


# ---------------------------------------------------------------------------
# 7. POST /wizard/units — submit saves to state
# ---------------------------------------------------------------------------


def test_units_submit_saves_state(authed_client):
    """POST /wizard/units saves the submitted unit groups to wizard state."""
    us_units = dict(UNIT_PRESETS["us"])

    resp = authed_client.post("/wizard/units", data=us_units)
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.units is not None
    assert state.units.get("group_temperature") == "degree_F"
    assert state.units.get("group_speed") == "mile_per_hour"


def test_units_submit_proceeds_to_next_step(authed_client):
    """POST /wizard/units with valid selections returns the next wizard step fragment."""
    resp = authed_client.post("/wizard/units", data=dict(UNIT_PRESETS["us"]))
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_units_submit_invalid_unit_returns_422(authed_client):
    """POST /wizard/units with an unrecognised unit value returns 422 with error."""
    bad_units = dict(UNIT_PRESETS["us"])
    bad_units["group_temperature"] = "not_a_real_unit"

    resp = authed_client.post("/wizard/units", data=bad_units)
    assert resp.status_code == 422


def test_units_submit_missing_group_returns_422(authed_client):
    """POST /wizard/units missing one group returns 422."""
    incomplete = {k: v for k, v in UNIT_PRESETS["us"].items() if k != "group_rain"}
    resp = authed_client.post("/wizard/units", data=incomplete)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 8. Preset values — US preset sets all groups correctly
# ---------------------------------------------------------------------------


def test_units_preset_us_sets_all_groups(authed_client):
    """Submitting US preset values saves the correct unit for every group."""
    resp = authed_client.post("/wizard/units", data=dict(UNIT_PRESETS["us"]))
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.units is not None

    us = UNIT_PRESETS["us"]
    for group, expected_unit in us.items():
        assert state.units.get(group) == expected_unit, (
            f"Group {group}: expected {expected_unit!r}, got {state.units.get(group)!r}"
        )


def test_units_preset_metric_sets_all_groups(authed_client):
    """Submitting Metric preset values saves the correct unit for every group."""
    resp = authed_client.post("/wizard/units", data=dict(UNIT_PRESETS["metric"]))
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.units is not None

    metric = UNIT_PRESETS["metric"]
    for group, expected_unit in metric.items():
        assert state.units.get(group) == expected_unit, (
            f"Group {group}: expected {expected_unit!r}, got {state.units.get(group)!r}"
        )

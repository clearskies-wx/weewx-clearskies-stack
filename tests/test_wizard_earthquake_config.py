"""Tests for earthquake configuration fields in wizard step 13 (feature settings).

Covers:
  - WizardState earthquake field defaults
  - POST /wizard/features saves earthquake config fields to state
  - POST /wizard/features clamps and validates field values
  - Apply payload uses 'default_radius_km' (not 'radius_km') for the API key name
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weewx_clearskies_config.wizard.state import WizardState, get_wizard_state, save_wizard_state


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


def _get_state(client) -> WizardState | None:
    """Return the WizardState associated with the client's session cookie."""
    session_cookie = client.cookies.get("clearskies_session")
    if not session_cookie:
        return None
    return get_wizard_state(session_cookie)


# ---------------------------------------------------------------------------
# Step 13 POST (/wizard/features) — earthquake config fields saved to state
# ---------------------------------------------------------------------------


def test_step8_post_saves_earthquake_radius_km(authed_client):
    """POST to /wizard/features with earthquake_radius_km saves the value to state."""
    resp = authed_client.post(
        "/wizard/features",
        data={
            "earthquake_radius_km": "250",
            "earthquake_min_magnitude": "2.0",
            "earthquake_default_days": "7",
        },
    )
    # /wizard/features POST advances to step 14 (review) — expect 200 HTML fragment.
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_radius_km == 250.0


def test_step8_post_saves_earthquake_min_magnitude(authed_client):
    """POST to /wizard/features with earthquake_min_magnitude saves the value to state."""
    authed_client.post(
        "/wizard/features",
        data={
            "earthquake_radius_km": "100",
            "earthquake_min_magnitude": "3.5",
            "earthquake_default_days": "7",
        },
    )

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_min_magnitude == 3.5


def test_step8_post_saves_earthquake_default_days(authed_client):
    """POST to /wizard/features with earthquake_default_days saves the value to state."""
    authed_client.post(
        "/wizard/features",
        data={
            "earthquake_radius_km": "100",
            "earthquake_min_magnitude": "2.0",
            "earthquake_default_days": "14",
        },
    )

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_default_days == 14


def test_step8_post_defaults_radius_when_value_missing(authed_client):
    """Missing earthquake_radius_km falls back to 100."""
    authed_client.post(
        "/wizard/features",
        data={
            "earthquake_min_magnitude": "2.0",
            "earthquake_default_days": "7",
        },
    )

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_radius_km == 100.0


def test_step8_post_rejects_invalid_days_and_falls_back_to_7(authed_client):
    """An invalid days value (not in 1/7/14/30) falls back to 7."""
    authed_client.post(
        "/wizard/features",
        data={
            "earthquake_radius_km": "100",
            "earthquake_min_magnitude": "2.0",
            "earthquake_default_days": "99",
        },
    )

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_default_days == 7


def test_step8_post_clamps_radius_to_minimum_of_1(authed_client):
    """earthquake_radius_km below 1 is clamped to 1.0."""
    authed_client.post(
        "/wizard/features",
        data={
            "earthquake_radius_km": "0",
            "earthquake_min_magnitude": "2.0",
            "earthquake_default_days": "7",
        },
    )

    state = _get_state(authed_client)
    assert state is not None
    assert state.earthquake_radius_km == 1.0


# ---------------------------------------------------------------------------
# Apply payload key name — 'default_radius_km' not 'radius_km'
# ---------------------------------------------------------------------------


def test_apply_payload_uses_default_radius_km_key():
    """The wizard apply handler must use 'default_radius_km' in the earthquakes payload.

    The API contract requires 'default_radius_km' (not 'radius_km').  This test
    reads the routes.py source to verify the key name, catching any regression
    where someone renames it back to the incorrect 'radius_km'.
    """
    import weewx_clearskies_config.wizard.routes as routes_mod
    import inspect

    source = inspect.getsource(routes_mod.wizard_apply)
    # The payload key must be 'default_radius_km', not the incorrect 'radius_km'.
    assert '"default_radius_km"' in source, (
        "Apply payload missing 'default_radius_km' key — "
        "check the api_payload['earthquakes'] dict in wizard_apply()"
    )
    # Verify the incorrect key is not used in the earthquakes section.
    # Find the earthquakes dict construction and check 'radius_km' only appears
    # as part of 'default_radius_km', not as a standalone key.
    lines = source.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('"radius_km"') or stripped.startswith("'radius_km'"):
            pytest.fail(
                f"Apply payload uses bare 'radius_km' key instead of 'default_radius_km': {line!r}"
            )

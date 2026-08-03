"""Tests for imagery provider fields on wizard step 6 (Providers & API Keys).

Phase LM / LM-3 — general-purpose orthophoto imagery provider (NOT marine-
specific), configured like any other external provider (API-MANUAL §12a).

Covers:
  - POST /wizard/step/6 saves provider_imagery (auto|naip|esri) to
    state.providers["imagery"]
  - Auto is the default when the field is omitted from the submission
  - imagery_api_key is saved to state (optional, not required)
  - wizard_apply()'s api_providers loop attaches the imagery api_key onto the
    ProviderConfig entry it builds for the "imagery" domain (source-inspection,
    same pattern as test_wizard_earthquake_config.py's apply-payload-key test
    — wizard_apply is a large integration route with real network side
    effects, not practical to exercise end-to-end in this suite)
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from weewx_clearskies_config.wizard.state import WizardState, get_wizard_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def authed_client(test_app, config_dir: Path):
    """TestClient with an active admin session (mirrors conftest.authed_client)."""
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
    session_cookie = client.cookies.get("clearskies_session")
    if not session_cookie:
        return None
    return get_wizard_state(session_cookie)


# ---------------------------------------------------------------------------
# KAT (a)/(b): provider_imagery selection saved to state.providers["imagery"]
# ---------------------------------------------------------------------------


def test_step6_post_saves_imagery_provider_naip(authed_client):
    resp = authed_client.post("/wizard/step/6", data={"provider_imagery": "naip"})
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.providers.get("imagery") == "naip"


def test_step6_post_saves_imagery_provider_esri(authed_client):
    resp = authed_client.post("/wizard/step/6", data={"provider_imagery": "esri"})
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.providers.get("imagery") == "esri"


def test_step6_post_saves_imagery_provider_auto(authed_client):
    resp = authed_client.post("/wizard/step/6", data={"provider_imagery": "auto"})
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.providers.get("imagery") == "auto"


def test_step6_post_defaults_imagery_provider_to_auto_when_omitted(authed_client):
    """The <select> always submits a value in the browser, but a client that omits
    the field entirely (or a malformed submission) must still default to Auto,
    matching API-MANUAL §12a's default and plan LM-3(a)."""
    resp = authed_client.post("/wizard/step/6", data={})
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.providers.get("imagery") == "auto"


# ---------------------------------------------------------------------------
# api_key field — optional, not required for submission
# ---------------------------------------------------------------------------


def test_step6_post_saves_imagery_api_key(authed_client):
    resp = authed_client.post(
        "/wizard/step/6",
        data={"provider_imagery": "naip", "imagery_api_key": "future-key-123"},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.imagery_api_key == "future-key-123"


def test_step6_post_imagery_api_key_not_required(authed_client):
    """Submitting without imagery_api_key must not fail or block the step —
    it is future-proofing only (API-MANUAL §12a); NAIP/ESRI do not use it."""
    resp = authed_client.post("/wizard/step/6", data={"provider_imagery": "esri"})
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state is not None
    assert state.imagery_api_key == ""


# ---------------------------------------------------------------------------
# wizard_apply() — payload wiring (source-inspection; wizard_apply is a large
# integration route with real network side effects — same rationale as
# test_wizard_earthquake_config.py's test_apply_payload_uses_default_radius_km_key)
# ---------------------------------------------------------------------------


def test_apply_payload_generic_provider_loop_covers_imagery_domain():
    """The existing generic `for domain, provider_id in state.providers.items()`
    loop in wizard_apply() must NOT special-case away the "imagery" domain —
    it should flow through the same ProviderConfig-building path as every
    other domain (forecast/alerts/aqi/earthquakes/radar), matching plan
    LM-3(d)'s "existing apply flow" instruction (no new endpoint/mechanism)."""
    import weewx_clearskies_config.wizard.routes as routes_mod

    source = inspect.getsource(routes_mod.wizard_apply)
    assert 'for domain, provider_id in state.providers.items():' in source
    # No branch that skips or special-cases the imagery domain out of the loop.
    assert 'domain != "imagery"' not in source
    assert 'domain == "imagery" and state.imagery_api_key' in source
    assert 'provider_entry["api_key"] = state.imagery_api_key' in source

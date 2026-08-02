"""Tests for the marine directional-exposure Auto/Override presentation (C9b).

Covers the backend send-paths' honoring of the frozen wire contract (absent
key = Auto/fan-derived, present non-empty key = manual override) plus the
wizard's restore-from-existing-config normalization fix. No template test
harness exists in this repo (see C9b scope-ack); these are the plain
module-level functions the templates and POST handlers call, and that the
templates' Jinja `exposure`/`exposure_is_override` variables are computed
from.

Regression guard only -- these do not exercise the HTML templates
themselves, only the data functions that feed them and receive their form
submissions.
"""

from __future__ import annotations

from typing import Any

from weewx_clearskies_config.admin.routes import (
    _build_marine_apply_payload,
    _parse_marine_locations,
)
from weewx_clearskies_config.wizard.config_writer import build_marine_payload
from weewx_clearskies_config.wizard.routes import _merge_from_api_current_config
from weewx_clearskies_config.wizard.state import WizardState


def _admin_surf_loc(directional_exposure: list[str] | None = None) -> dict[str, Any]:
    """Minimal admin-shaped location dict, as returned by _parse_marine_locations
    and consumed by _build_marine_apply_payload."""
    surf: dict[str, Any] = {
        "segment_start_lat": 34.2, "segment_start_lon": -77.8,
        "segment_end_lat": 34.21, "segment_end_lon": -77.79,
        "bottom_type": "sand", "topographic_feature": "straight_beach",
    }
    if directional_exposure is not None:
        surf["directional_exposure"] = directional_exposure
    return {
        "name": "Test Beach", "lat": 34.2, "lon": -77.8,
        "activities": ["surf"], "surf": surf,
    }


# ---------------------------------------------------------------------------
# admin/routes.py: _parse_marine_locations -- reading on-disk config back in
# ---------------------------------------------------------------------------

def test_parse_marine_locations_absent_key_is_auto():
    cfg = {"locations": {"spot1": {
        "name": "Spot 1", "lat": 1.0, "lon": 2.0, "activities": ["surf"],
        "surf": {"bottom_type": "sand", "topographic_feature": "point_break"},
    }}}
    parsed = _parse_marine_locations(cfg)
    assert parsed["spot1"]["directional_exposure_is_override"] is False
    assert parsed["spot1"]["surf"]["directional_exposure"] == []


def test_parse_marine_locations_present_dict_is_override():
    cfg = {"locations": {"spot1": {
        "name": "Spot 1", "lat": 1.0, "lon": 2.0, "activities": ["surf"],
        "surf": {
            "bottom_type": "sand", "topographic_feature": "point_break",
            "directional_exposure": {"N": True, "NE": False, "SE": True},
        },
    }}}
    parsed = _parse_marine_locations(cfg)
    assert parsed["spot1"]["directional_exposure_is_override"] is True
    assert parsed["spot1"]["surf"]["directional_exposure"] == ["N", "SE"]


def test_parse_marine_locations_present_empty_dict_is_still_override():
    """An override that blocks every direction is still an override -- key
    presence, not truthiness, decides the display mode (parity with the
    marine service's own directional_exposure_is_override)."""
    cfg = {"locations": {"spot1": {
        "name": "Spot 1", "lat": 1.0, "lon": 2.0, "activities": ["surf"],
        "surf": {
            "bottom_type": "sand", "topographic_feature": "point_break",
            "directional_exposure": {},
        },
    }}}
    parsed = _parse_marine_locations(cfg)
    assert parsed["spot1"]["directional_exposure_is_override"] is True
    assert parsed["spot1"]["surf"]["directional_exposure"] == []


def test_parse_marine_locations_no_surf_activity_is_not_override():
    cfg = {"locations": {"spot1": {
        "name": "Spot 1", "lat": 1.0, "lon": 2.0, "activities": ["marine"],
    }}}
    parsed = _parse_marine_locations(cfg)
    assert parsed["spot1"]["directional_exposure_is_override"] is False


# ---------------------------------------------------------------------------
# admin/routes.py: _build_marine_apply_payload -- the actual send path
# ---------------------------------------------------------------------------

def test_build_marine_apply_payload_auto_key_absent():
    locations = {"spot1": _admin_surf_loc(directional_exposure=[])}
    payload = _build_marine_apply_payload({}, locations)
    surf_out = payload["marine"]["locations"][0]["surf"]
    assert "directional_exposure" not in surf_out


def test_build_marine_apply_payload_override_key_present():
    locations = {"spot1": _admin_surf_loc(directional_exposure=["N", "SE"])}
    payload = _build_marine_apply_payload({}, locations)
    surf_out = payload["marine"]["locations"][0]["surf"]
    assert surf_out["directional_exposure"] == {"N": True, "SE": True}


def test_build_marine_apply_payload_override_to_auto_removes_key():
    """Simulates the admin toggle being switched back to Auto and saved --
    the parsed location's exposure list is now empty; the key must be
    removed from the outgoing payload, not sent as an empty dict."""
    overridden = _admin_surf_loc(directional_exposure=["N"])
    payload_before = _build_marine_apply_payload({}, {"spot1": overridden})
    assert "directional_exposure" in payload_before["marine"]["locations"][0]["surf"]

    reverted = _admin_surf_loc(directional_exposure=[])
    payload_after = _build_marine_apply_payload({}, {"spot1": reverted})
    assert "directional_exposure" not in payload_after["marine"]["locations"][0]["surf"]


# ---------------------------------------------------------------------------
# wizard/config_writer.py: build_marine_payload -- the wizard's send path
# ---------------------------------------------------------------------------

def _wizard_state_with_location(directional_exposure: list[str] | None = None) -> WizardState:
    """directional_exposure=None means "key never set" (Auto) -- matches
    step_marine_post's own `if exposure: surf_cfg["directional_exposure"] =
    exposure` gate, which never writes an empty-but-present list into state.
    """
    surf: dict[str, Any] = {
        "segment_start_lat": 34.2, "segment_start_lon": -77.8,
        "segment_end_lat": 34.21, "segment_end_lon": -77.79,
        "bottom_type": "sand", "topographic_feature": "straight_beach",
    }
    if directional_exposure is not None:
        surf["directional_exposure"] = directional_exposure
    return WizardState(
        marine_enabled=True,
        marine_locations={
            "spot1": {
                "name": "Test Beach", "lat": 34.2, "lon": -77.8,
                "activities": ["surf"], "surf": surf,
            }
        },
    )


def test_wizard_build_marine_payload_auto_key_absent():
    state = _wizard_state_with_location(directional_exposure=None)
    payload = build_marine_payload(state)
    surf_out = payload["locations"][0]["surf"]
    assert "directional_exposure" not in surf_out


def test_wizard_build_marine_payload_override_key_present():
    state = _wizard_state_with_location(directional_exposure=["N", "SE"])
    payload = build_marine_payload(state)
    surf_out = payload["locations"][0]["surf"]
    assert surf_out["directional_exposure"] == {"N": True, "SE": True}


def test_wizard_build_marine_payload_override_to_auto_removes_key():
    state_before = _wizard_state_with_location(directional_exposure=["N"])
    payload_before = build_marine_payload(state_before)
    assert "directional_exposure" in payload_before["locations"][0]["surf"]

    state_after = _wizard_state_with_location(directional_exposure=None)
    payload_after = build_marine_payload(state_after)
    assert "directional_exposure" not in payload_after["locations"][0]["surf"]


# ---------------------------------------------------------------------------
# wizard/routes.py: _merge_from_api_current_config -- restore-on-rerun path
# (C9b bug fix: a dict-shaped exposure must normalize to a checked-directions
# list, not render every direction checked via `dir in exposure` dict-key
# membership; and the normalized state must never carry an empty-but-present
# list, which config_writer.py's isinstance(list)-gated branch -- unlike the
# truthy gates used everywhere else -- would send as an empty-dict override.)
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def get_current_config(self) -> dict[str, Any]:
        return self._config


def _restore_one_location(surf_raw: dict[str, Any]) -> dict[str, Any]:
    config = {"marine": {"locations": {"spot1": {
        "name": "Spot 1", "lat": 1.0, "lon": 2.0, "activities": ["surf"],
        "surf": surf_raw,
    }}}}
    state = WizardState()
    _merge_from_api_current_config(_FakeClient(config), state)
    return state.marine_locations["spot1"]


def test_restore_override_dict_only_true_directions_checked():
    restored = _restore_one_location({
        "bottom_type": "sand", "topographic_feature": "point_break",
        "directional_exposure": {"N": True, "NE": False, "SE": True, "S": False},
    })
    assert restored["directional_exposure_is_override"] is True
    assert restored["surf"]["directional_exposure"] == ["N", "SE"]


def test_restore_absent_exposure_is_auto():
    restored = _restore_one_location({
        "bottom_type": "sand", "topographic_feature": "point_break",
    })
    assert restored["directional_exposure_is_override"] is False
    assert "directional_exposure" not in restored["surf"]


def test_restore_all_false_override_is_override_mode_with_no_directions_checked():
    """An on-disk override that blocks every direction: displays as Override
    (key was present) but the checked-directions list is empty, and the key
    stays ABSENT from state's surf dict (not an empty list) so an untouched
    re-apply doesn't silently resend it as a fresh empty-dict override via
    config_writer.py's isinstance(list) branch."""
    restored = _restore_one_location({
        "bottom_type": "sand", "topographic_feature": "point_break",
        "directional_exposure": {"N": False, "S": False},
    })
    assert restored["directional_exposure_is_override"] is True
    assert "directional_exposure" not in restored["surf"]


def test_restore_then_untouched_reapply_keeps_auto_key_absent():
    """Regression guard for the restore-fix's interaction with
    build_marine_payload(): restoring an Auto location and immediately
    re-applying without editing it must still omit the key."""
    restored = _restore_one_location({
        "bottom_type": "sand", "topographic_feature": "point_break",
    })
    state = WizardState(marine_enabled=True, marine_locations={"spot1": restored})
    payload = build_marine_payload(state)
    assert "directional_exposure" not in payload["locations"][0]["surf"]


# ---------------------------------------------------------------------------
# Route-level smoke tests -- confirm the templates actually render (catches
# Jinja runtime errors, e.g. undefined attribute access, that a pure
# env.parse() syntax check cannot). No template-diffing/DOM assertions --
# just presence of the expected mode labels in the rendered HTML.
# ---------------------------------------------------------------------------

_MARINE_CONFIG_TWO_LOCATIONS: dict[str, Any] = {
    "marine": {
        "locations": {
            "auto_spot": {
                "name": "Auto Spot", "lat": 34.0, "lon": -77.0,
                "activities": ["surf"],
                "surf": {
                    "segment_start_lat": 34.0, "segment_start_lon": -77.0,
                    "segment_end_lat": 34.01, "segment_end_lon": -77.01,
                    "bottom_type": "sand", "topographic_feature": "straight_beach",
                },
            },
            "override_spot": {
                "name": "Override Spot", "lat": 35.0, "lon": -78.0,
                "activities": ["surf"],
                "surf": {
                    "segment_start_lat": 35.0, "segment_start_lon": -78.0,
                    "segment_end_lat": 35.01, "segment_end_lon": -78.01,
                    "bottom_type": "rock", "topographic_feature": "point_break",
                    "directional_exposure": {"N": True, "SE": True},
                },
            },
        }
    },
    "database": {}, "station": {},
}


class _FakeRouteClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def get_current_config(self) -> dict[str, Any]:
        return self._config


def test_admin_marine_list_shows_auto_and_override_modes(authed_client, monkeypatch):
    import weewx_clearskies_config.admin.routes as admin_routes

    monkeypatch.setattr(
        admin_routes, "_get_api_client",
        lambda: _FakeRouteClient(_MARINE_CONFIG_TWO_LOCATIONS),
    )

    resp = authed_client.get("/admin/marine", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "Auto (measured)" in body
    assert "Override" in body
    assert "N, SE" in body


def test_admin_marine_edit_form_override_location_checks_only_true_directions(
    authed_client, monkeypatch
):
    import weewx_clearskies_config.admin.routes as admin_routes

    monkeypatch.setattr(
        admin_routes, "_get_api_client",
        lambda: _FakeRouteClient(_MARINE_CONFIG_TWO_LOCATIONS),
    )

    resp = authed_client.post(
        "/admin/marine/edit",
        data={"location_id": "override_spot"},
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200
    body = resp.text
    assert 'value="override"' in body and "checked" in body
    # Only N and SE were true in the source dict -- confirm the checkbox
    # markup for N is checked and for (e.g.) W is not, by proximity to the
    # value attribute (loose smoke check, not full DOM parsing).
    n_idx = body.find('value="N"')
    w_idx = body.find('value="W"')
    assert n_idx != -1 and w_idx != -1
    assert "checked" in body[n_idx:n_idx + 40]
    assert "checked" not in body[w_idx:w_idx + 40]


def test_wizard_marine_get_renders_override_location(authed_client):
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie
    state = get_wizard_state(session_cookie)
    state.marine_enabled = True
    state.marine_locations = {
        "spot1": {
            "name": "Test Spot", "lat": 34.0, "lon": -77.0,
            "activities": ["surf"],
            "surf": {
                "segment_start_lat": 34.0, "segment_start_lon": -77.0,
                "segment_end_lat": 34.01, "segment_end_lon": -77.01,
                "bottom_type": "sand", "topographic_feature": "straight_beach",
                "directional_exposure": ["N", "SE"],
            },
        }
    }
    save_wizard_state(session_cookie, state)

    resp = authed_client.get("/wizard/marine")

    assert resp.status_code == 200
    body = resp.text
    assert "Manual override" in body
    assert "Auto (measured)" in body

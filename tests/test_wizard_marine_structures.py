"""Tests for the wizard's marine structure geometry round-trip (G6.3).

Wizard-side counterpart to tests/test_admin_marine_structures.py, added to
close the coverage gap found during the G6.3 scope-ack: the admin panel has
a standalone form-parse function pair (_validate_marine_location_form /
_build_marine_apply_payload) that's directly unit-testable, but the wizard's
equivalent parsing (wizard/routes.py:2961-2996, inside step_marine_post) is
inline in an async route handler with no extracted pure function -- so these
tests exercise it the same way test_marine_exposure_override.py's route-level
tests do: POST through the real /wizard/marine route via a session-scoped
TestClient, then read the saved WizardState back and feed it through
wizard/config_writer.py's build_marine_payload() (the wizard's send-path
counterpart to _build_marine_apply_payload).

Covers the plan's binding wizard/admin parity ruling (MARINE-FORWARD-PLAN
G6.3) -- both surfaces now enable L.Draw.Polygon and both surfaces' round
trips are covered by a test.
"""

from __future__ import annotations

import json
from typing import Any

from weewx_clearskies_config.wizard.config_writer import build_marine_payload
from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state


def _base_marine_post_fields(session_cookie: str) -> None:
    """Seed the wizard session with a marine_service_url so step_marine_post
    doesn't 422 before reaching the location-parsing code under test (T7.4
    check at wizard/routes.py:3114)."""
    state = get_wizard_state(session_cookie)
    state.marine_service_url = "http://fake-marine.invalid:8780"
    save_wizard_state(session_cookie, state)


def _surf_location_fields(idx: int = 0) -> dict[str, str]:
    p = f"loc_{idx}_"
    return {
        f"{p}name": "Test Beach",
        f"{p}lat": "33.6553",
        f"{p}lon": "-118.0067",
        f"{p}activities": "surf",
        f"{p}surf_segment_start_lat": "33.65",
        f"{p}surf_segment_start_lon": "-118.00",
        f"{p}surf_segment_end_lat": "33.66",
        f"{p}surf_segment_end_lon": "-118.01",
        f"{p}surf_bottom_type": "sand",
        f"{p}surf_topographic_feature": "straight_beach",
    }


# ---------------------------------------------------------------------------
# Polyline round trip -- pins the pre-existing (MUST-NOT-TOUCH) flow. Not a
# new capability; this is the golden assertion the brief asks for, now
# exercised end to end (HTTP form-parse -> WizardState -> apply payload) for
# the first time on the wizard side.
# ---------------------------------------------------------------------------

def test_wizard_save_with_drawn_polyline_coordinates_round_trip_byte_faithful(authed_client):
    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie
    _base_marine_post_fields(session_cookie)

    coordinates = [[-118.0067, 33.6553], [-118.0090, 33.6551], [-118.0113, 33.6549]]
    fields = {
        **_surf_location_fields(),
        "marine_enabled": "1",
        "loc_0_structure_0_type": "pier",
        "loc_0_structure_0_material": "permeable",
        "loc_0_structure_0_length_m": "610.0",
        "loc_0_structure_0_bearing_degrees": "245.0",
        "loc_0_structure_0_distance_m": "45.2",
        "loc_0_structure_0_coordinates": json.dumps(coordinates),
    }
    resp = authed_client.post("/wizard/marine", data=fields)
    assert resp.status_code == 200

    state = get_wizard_state(session_cookie)
    structures = state.marine_locations["test-beach"]["surf"]["structures"]
    assert len(structures) == 1
    assert structures[0]["coordinates"] == coordinates  # byte-faithful, same value

    payload = build_marine_payload(state)
    sent = payload["locations"][0]["surf"]["structures"][0]["coordinates"]
    assert sent == coordinates
    assert json.loads(json.dumps(sent)) == coordinates


# ---------------------------------------------------------------------------
# G6.3: polygon closed-ring round trip. Ring-closure convention (operator
# ruling 2026-08-03): the template's JS writes a drawn polygon first==last
# on the wire -- these KATs assert that closed ring survives the wizard's
# form-parse -> WizardState -> apply-payload path byte-faithfully, same as
# the polyline case, through the SAME loc_{n}_structure_{m}_coordinates
# JSON-string field (frozen E13 contract, no new field).
# ---------------------------------------------------------------------------

def test_wizard_save_with_drawn_polygon_coordinates_closed_ring_round_trip_byte_faithful(
    authed_client,
):
    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie
    _base_marine_post_fields(session_cookie)

    ring = [
        [-118.0067, 33.6553],
        [-118.0090, 33.6551],
        [-118.0113, 33.6549],
        [-118.0067, 33.6553],  # closing vertex == first vertex
    ]
    assert ring[0] == ring[-1]  # sanity: fixture itself is a closed ring

    fields = {
        **_surf_location_fields(),
        "marine_enabled": "1",
        "loc_0_structure_0_type": "breakwater",
        "loc_0_structure_0_material": "impermeable",
        "loc_0_structure_0_length_m": "300.0",
        "loc_0_structure_0_bearing_degrees": "10.0",
        "loc_0_structure_0_distance_m": "120.0",
        "loc_0_structure_0_coordinates": json.dumps(ring),
    }
    resp = authed_client.post("/wizard/marine", data=fields)
    assert resp.status_code == 200

    state = get_wizard_state(session_cookie)
    structures = state.marine_locations["test-beach"]["surf"]["structures"]
    assert len(structures) == 1
    assert structures[0]["coordinates"] == ring  # byte-faithful, same value
    assert structures[0]["coordinates"][0] == structures[0]["coordinates"][-1]  # still closed

    payload = build_marine_payload(state)
    sent = payload["locations"][0]["surf"]["structures"][0]["coordinates"]
    assert sent == ring
    assert sent[0] == sent[-1]  # closure survives the apply-payload build too
    assert json.loads(json.dumps(sent)) == ring


def test_wizard_save_without_structure_coordinates_never_fabricates_any(authed_client):
    """ADR-095 Decision 3, wizard side: a manually-entered structure with no
    drawn/discovered geometry gets no coordinates key anywhere downstream."""
    session_cookie = authed_client.cookies.get("clearskies_session")
    assert session_cookie
    _base_marine_post_fields(session_cookie)

    fields = {
        **_surf_location_fields(),
        "marine_enabled": "1",
        "loc_0_structure_0_type": "jetty",
        "loc_0_structure_0_material": "semi_permeable",
        "loc_0_structure_0_length_m": "200.0",
        "loc_0_structure_0_bearing_degrees": "90.0",
        "loc_0_structure_0_distance_m": "30.0",
        # No loc_0_structure_0_coordinates field at all.
    }
    resp = authed_client.post("/wizard/marine", data=fields)
    assert resp.status_code == 200

    state = get_wizard_state(session_cookie)
    structures = state.marine_locations["test-beach"]["surf"]["structures"]
    assert len(structures) == 1
    assert "coordinates" not in structures[0]

    payload = build_marine_payload(state)
    sent_structure = payload["locations"][0]["surf"]["structures"][0]
    assert "coordinates" not in sent_structure


# ---------------------------------------------------------------------------
# G6.3: polygon-availability + polyline-byte-identical source guards.
# templates/wizard/step_marine.html has no dedicated JS test harness (see
# test_marine_exposure_override.py's module docstring for the repo-wide
# precedent) -- these read the rendered template source directly.
# ---------------------------------------------------------------------------

def _wizard_marine_template_source() -> str:
    from pathlib import Path
    import weewx_clearskies_config

    path = (
        Path(weewx_clearskies_config.__file__).parent
        / "templates" / "wizard" / "step_marine.html"
    )
    return path.read_text(encoding="utf-8")


def test_wizard_marine_template_polygon_draw_enabled():
    """L.Control.Draw's polygon option must be an enabled shape config, not
    `false` -- this is the actual G6.3 change. Mutation-falsifiable: revert
    the polygon line back to `polygon: false,` and this fails."""
    src = _wizard_marine_template_source()
    assert 'polygon: { shapeOptions: { color: "#e63946", weight: 4, opacity: 0.85 } },' in src
    assert "polygon: false," not in src


def test_wizard_marine_template_polyline_draw_config_unchanged():
    """The polyline draw config -- the MUST-NOT-TOUCH flow -- is byte-
    identical to its pre-G6.3 value."""
    src = _wizard_marine_template_source()
    assert 'polyline: { shapeOptions: { color: "#e63946", weight: 4, opacity: 0.85 } },' in src


def test_wizard_marine_template_polygon_ring_closure_write_present():
    """The CREATED handler must explicitly close a drawn polygon's ring
    (push the first vertex back on as the last) before it reaches
    createStructureCard()/JSON.stringify -- this is the client-side half of
    the closed-ring convention the round-trip KATs above assume as their
    input. Mutation-falsifiable: delete the `coordinates.push(...)` line and
    this fails (the Python-level round-trip tests above cannot catch this on
    their own since they construct an already-closed ring as input and never
    execute this JS)."""
    src = _wizard_marine_template_source()
    assert 'if (e.layerType === "polygon" && coordinates.length > 1) {' in src
    assert "coordinates.push([firstPt[0], firstPt[1]]);" in src

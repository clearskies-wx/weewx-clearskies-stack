"""Tests for the admin marine "Coastal Structures" origination capability
(R-ADMIN-1 discover, R-ADMIN-2 draw) -- Marine Forward Plan, INV-STRUCTURES
closeout.

Before this round, the admin panel could only round-trip a structure's
``coordinates`` if the on-disk config already carried them (no discover, no
draw) -- the gap that let the 2026-08-02 admin save silently drop the pier's
polyline. These tests cover the two new capabilities plus the guard that
made the original clobber possible: a structure without geometry must never
have coordinates fabricated for it.

Mirrors test_admin_status.py's pattern: monkeypatch admin.routes._get_api_client
with a fake client so no real network call is ever made (the marine service
is reached only through the API, per ARCHITECTURE.md). KAT (a) exercises the
new HTTP route end to end; KATs (b)/(c) exercise the pure form-parsing /
apply-payload functions directly (same approach as
test_marine_exposure_override.py -- "No template test harness exists in
this repo" for exercising the Jinja templates themselves).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.datastructures import FormData

from weewx_clearskies_config.admin.routes import (
    _build_marine_apply_payload,
    _validate_marine_location_form,
)


# ---------------------------------------------------------------------------
# KAT (a): discover route proxies the API and renders selectable cards
# ---------------------------------------------------------------------------

class _FakeDiscoverApiClient:
    """Stand-in for ApiClient -- only .discover_structures() is used by the
    new admin route."""

    def __init__(self, *, structures: list[dict[str, Any]] | None = None,
                 raises: bool = False) -> None:
        self._structures = structures if structures is not None else []
        self._raises = raises
        self.calls: list[tuple[float, float, int]] = []

    def discover_structures(self, lat: float, lon: float, radius_m: int = 2000) -> dict[str, Any]:
        self.calls.append((lat, lon, radius_m))
        if self._raises:
            raise RuntimeError("connection failed")
        return {"structures": self._structures}


# A realistic Overpass-derived payload (shape matches MarineDiscoveredStructure
# as consumed by the wizard's identical route, wizard/routes.py:3376-3419):
# way 45074900-style pier, geometry as [[lat, lon], ...].
_REALISTIC_PIER_PAYLOAD = [
    {
        "type": "pier",
        "name": "Huntington Beach Pier",
        "distance_m": 45.2,
        "length_m": 610.0,
        "bearing_degrees": 245.0,
        "material": "permeable",
        "material_source": "osm",
        "geometry": [
            [33.6553, -118.0067],
            [33.6551, -118.0090],
            [33.6549, -118.0113],
        ],
    },
    {
        "type": "breakwater",
        "name": None,
        "distance_m": 812.5,
        "length_m": 120.0,
        "bearing_degrees": 10.0,
        "material": None,
        "material_source": "operator",
        "geometry": [[33.66, -118.01], [33.661, -118.011]],
    },
]


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    import weewx_clearskies_config.admin.routes as routes

    monkeypatch.setattr(routes, "_get_api_client", lambda: client)


def test_discover_structures_renders_selectable_cards(authed_client, monkeypatch):
    client = _FakeDiscoverApiClient(structures=_REALISTIC_PIER_PAYLOAD)
    _patch_client(monkeypatch, client)

    resp = authed_client.post(
        "/admin/marine/discover-structures",
        data={"lat": "33.6553", "lon": "-118.0067"},
    )
    assert resp.status_code == 200
    body = resp.text

    # Proxies the existing API endpoint exactly -- same call shape as the
    # wizard's identical route.
    assert client.calls == [(33.6553, -118.0067, 2000)]

    # Renders a selectable checkbox per discovered structure.
    assert body.count('class="admin-discovered-structure-check"') == 2
    assert "Huntington Beach Pier" in body
    assert "Found 2 structures" in body

    # Geometry carried in data-geometry for client-side [lat,lon]->[lon,lat]
    # conversion on check -- same contract as the wizard. Geometry is a
    # numeric-only nested array (no & < > chars), so _marine_esc is a no-op
    # here and the embedded JSON is byte-identical to json.dumps().
    assert "data-geometry=" in body
    geom_marker = json.dumps(_REALISTIC_PIER_PAYLOAD[0]["geometry"])
    assert geom_marker in body

    # No stale bearing_to_spot_degrees field anywhere in the rendered output.
    assert "bearing_to_spot_degrees" not in body


def test_discover_structures_no_coordinates_shows_prompt(authed_client, monkeypatch):
    client = _FakeDiscoverApiClient(structures=_REALISTIC_PIER_PAYLOAD)
    _patch_client(monkeypatch, client)

    resp = authed_client.post("/admin/marine/discover-structures", data={})
    assert resp.status_code == 200
    assert "Enter coordinates" in resp.text
    assert client.calls == []


def test_discover_structures_none_found(authed_client, monkeypatch):
    client = _FakeDiscoverApiClient(structures=[])
    _patch_client(monkeypatch, client)

    resp = authed_client.post(
        "/admin/marine/discover-structures",
        data={"lat": "10.0", "lon": "20.0"},
    )
    assert resp.status_code == 200
    assert "No structures found" in resp.text


def test_discover_structures_api_unreachable(authed_client, monkeypatch):
    _patch_client(monkeypatch, None)

    resp = authed_client.post(
        "/admin/marine/discover-structures",
        data={"lat": "10.0", "lon": "20.0"},
    )
    assert resp.status_code == 200
    assert "API unreachable" in resp.text


def test_discover_structures_api_error(authed_client, monkeypatch):
    client = _FakeDiscoverApiClient(raises=True)
    _patch_client(monkeypatch, client)

    resp = authed_client.post(
        "/admin/marine/discover-structures",
        data={"lat": "10.0", "lon": "20.0"},
    )
    assert resp.status_code == 200
    assert "Could not discover structures" in resp.text


# ---------------------------------------------------------------------------
# KATs (b) + (c): coordinates round-trip byte-faithfully through the apply
# payload when present, and are never fabricated when absent (ADR-095
# Decision 3). Exercises _validate_marine_location_form (the hidden
# structure_{n}_coordinates field parser, admin/routes.py:2189-2216) feeding
# _build_marine_apply_payload (the /setup/apply payload builder) --
# the same two functions the real /admin/marine/save route calls.
# ---------------------------------------------------------------------------

def _base_surf_form_fields() -> dict[str, str]:
    return {
        "name": "Test Beach",
        "lat": "33.6553",
        "lon": "-118.0067",
        "activities": "surf",
        "surf_segment_start_lat": "33.65",
        "surf_segment_start_lon": "-118.00",
        "surf_segment_end_lat": "33.66",
        "surf_segment_end_lon": "-118.01",
        "surf_bottom_type": "sand",
        "surf_topographic_feature": "straight_beach",
    }


def test_save_with_drawn_structure_coordinates_round_trip_byte_faithful():
    """A drawn/discovered structure's coordinates survive form-parse ->
    apply-payload build as the exact same [[lon,lat],...] JSON-decoded list
    (E13 frozen encoding) -- no re-ordering, no truncation, no re-derivation."""
    coordinates = [[-118.0067, 33.6553], [-118.0090, 33.6551], [-118.0113, 33.6549]]
    fields = list(_base_surf_form_fields().items()) + [
        ("structure_0_type", "pier"),
        ("structure_0_material", "permeable"),
        ("structure_0_length_m", "610.0"),
        ("structure_0_bearing_degrees", "245.0"),
        ("structure_0_distance_m", "45.2"),
        ("structure_0_coordinates", json.dumps(coordinates)),
    ]
    form = FormData(fields)

    location, error = _validate_marine_location_form(form)
    assert error is None
    assert location is not None
    structures = location["surf"]["structures"]
    assert len(structures) == 1
    assert structures[0]["coordinates"] == coordinates  # byte-faithful, same value

    payload = _build_marine_apply_payload(
        {"database": {}, "station": {}}, {"test-beach": location}
    )
    sent = payload["marine"]["locations"][0]["surf"]["structures"][0]["coordinates"]
    assert sent == coordinates
    # JSON round-trip is exact, not just equal-by-coincidence.
    assert json.loads(json.dumps(sent)) == coordinates


def test_save_without_structure_coordinates_never_fabricates_any():
    """A structure with no drawn/discovered geometry (manual entry, or the
    wizard's own pre-E13 gap) gets NO coordinates key anywhere downstream --
    ADR-095 Decision 3: never fabricate coordinates from bearing/length."""
    fields = list(_base_surf_form_fields().items()) + [
        ("structure_0_type", "jetty"),
        ("structure_0_material", "semi_permeable"),
        ("structure_0_length_m", "200.0"),
        ("structure_0_bearing_degrees", "90.0"),
        ("structure_0_distance_m", "30.0"),
        # No structure_0_coordinates field at all.
    ]
    form = FormData(fields)

    location, error = _validate_marine_location_form(form)
    assert error is None
    assert location is not None
    structures = location["surf"]["structures"]
    assert len(structures) == 1
    assert "coordinates" not in structures[0]

    payload = _build_marine_apply_payload(
        {"database": {}, "station": {}}, {"test-jetty": location}
    )
    sent_structure = payload["marine"]["locations"][0]["surf"]["structures"][0]
    assert "coordinates" not in sent_structure
    # Confirm no fabrication from bearing/length/distance -- those fields
    # are present and distinct from a coordinates key.
    assert sent_structure["bearing_degrees"] == 90.0
    assert sent_structure["length_m"] == 200.0
    assert sent_structure["distance_m"] == 30.0


def test_save_structure_coordinates_empty_string_does_not_fabricate():
    """The template renders the hidden field as value='null' when a
    structure has no coordinates (Jinja `| tojson` of None) -- confirm the
    parser treats that the same as absent, not as a fabricated [null]."""
    fields = list(_base_surf_form_fields().items()) + [
        ("structure_0_type", "groin"),
        ("structure_0_material", "impermeable"),
        ("structure_0_length_m", "50.0"),
        ("structure_0_bearing_degrees", "0.0"),
        ("structure_0_distance_m", "10.0"),
        ("structure_0_coordinates", "null"),
    ]
    form = FormData(fields)

    location, error = _validate_marine_location_form(form)
    assert error is None
    assert "coordinates" not in location["surf"]["structures"][0]


# ---------------------------------------------------------------------------
# G6.3: admin polygon draw tool. The admin-panel side of the plan's binding
# wizard/admin parity ruling -- templates/admin/marine.html's L.Control.Draw
# now enables L.Draw.Polygon alongside the polyline (was `polygon: false`).
# The captured ring flows through the SAME structure_{n}_coordinates
# JSON-string hidden field as a drawn polyline (frozen E13 contract) -- no
# new field, no shape change. Ring-closure convention (operator ruling
# 2026-08-03): a drawn polygon is written first==last on the wire by the
# template's JS before JSON.stringify, matching OSM's own closed-way
# convention (this contract's primary data source). The parser itself
# enforces no closure rule -- it accepts any non-empty JSON list of
# [lon,lat] pairs verbatim, open or closed; these KATs assert the *closed*
# ring the browser now sends survives round-trip byte-faithfully, not that
# the server enforces closure.
# ---------------------------------------------------------------------------

def test_save_with_drawn_polygon_coordinates_closed_ring_round_trip_byte_faithful():
    """A drawn polygon's closed ring (first==last, as the template's JS now
    writes it) survives form-parse -> apply-payload build byte-faithfully,
    same as the polyline case above -- same field, same contract, no
    reordering/dedup/truncation, and the closing vertex is neither added
    nor dropped by the server-side parser."""
    ring = [
        [-118.0067, 33.6553],
        [-118.0090, 33.6551],
        [-118.0113, 33.6549],
        [-118.0067, 33.6553],  # closing vertex == first vertex
    ]
    assert ring[0] == ring[-1]  # sanity: the fixture itself is a closed ring

    fields = list(_base_surf_form_fields().items()) + [
        ("structure_0_type", "breakwater"),
        ("structure_0_material", "impermeable"),
        ("structure_0_length_m", "300.0"),
        ("structure_0_bearing_degrees", "10.0"),
        ("structure_0_distance_m", "120.0"),
        ("structure_0_coordinates", json.dumps(ring)),
    ]
    form = FormData(fields)

    location, error = _validate_marine_location_form(form)
    assert error is None
    assert location is not None
    structures = location["surf"]["structures"]
    assert len(structures) == 1
    assert structures[0]["coordinates"] == ring  # byte-faithful, same value
    assert structures[0]["coordinates"][0] == structures[0]["coordinates"][-1]  # still closed

    payload = _build_marine_apply_payload(
        {"database": {}, "station": {}}, {"test-breakwater": location}
    )
    sent = payload["marine"]["locations"][0]["surf"]["structures"][0]["coordinates"]
    assert sent == ring
    assert sent[0] == sent[-1]  # closure survives the apply-payload build too
    # JSON round-trip is exact, not just equal-by-coincidence.
    assert json.loads(json.dumps(sent)) == ring


# ---------------------------------------------------------------------------
# G6.3: polygon-availability + polyline-byte-identical source guards.
# templates/admin/marine.html has no dedicated JS test harness (see module
# docstring) -- these read the rendered template source directly, the same
# escape hatch used elsewhere in this repo for template behavior that can't
# be exercised through the pure Python functions above.
# ---------------------------------------------------------------------------

def _admin_marine_template_source() -> str:
    from pathlib import Path
    import weewx_clearskies_config

    path = (
        Path(weewx_clearskies_config.__file__).parent
        / "templates" / "admin" / "marine.html"
    )
    return path.read_text(encoding="utf-8")


def test_admin_marine_template_polygon_draw_enabled():
    """L.Control.Draw's polygon option must be an enabled shape config, not
    `false` -- this is the actual G6.3 change. Mutation-falsifiable: revert
    the polygon line back to `polygon: false,` and this fails."""
    src = _admin_marine_template_source()
    assert 'polygon: { shapeOptions: { color: "#e63946", weight: 4, opacity: 0.85 } },' in src
    assert "polygon: false," not in src


def test_admin_marine_template_polyline_draw_config_unchanged():
    """The polyline draw config -- the MUST-NOT-TOUCH flow -- is byte-
    identical to its pre-G6.3 value."""
    src = _admin_marine_template_source()
    assert 'polyline: { shapeOptions: { color: "#e63946", weight: 4, opacity: 0.85 } },' in src


def test_admin_marine_template_polygon_ring_closure_write_present():
    """Mirrors the wizard's identical guard (test_wizard_marine_structures.py)
    -- the CREATED handler must explicitly close a drawn polygon's ring
    before it reaches adminCreateDrawnStructureCard()/JSON.stringify.
    Mutation-falsifiable: delete the `coordinates.push(...)` line and this
    fails."""
    src = _admin_marine_template_source()
    assert 'if (e.layerType === "polygon" && coordinates.length > 1) {' in src
    assert "coordinates.push([firstPt[0], firstPt[1]]);" in src

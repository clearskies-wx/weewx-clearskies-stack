"""Guard tests for the admin Status page (B4, Marine Model Restoration Plan).

Regression guard only -- not evidence the live system works. Mocks
_get_api_client() so no real network call is ever made; the marine service
is never contacted directly, per ARCHITECTURE.md's "add-on reached only
through the API" invariant.
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeResponse:
    """Minimal stand-in for httpx.Response -- only .json() is used."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeApiClient:
    """Stand-in for ApiClient -- only .health() and ._request() are used
    by the status page.
    """

    def __init__(
        self,
        *,
        api_healthy: bool = True,
        health_raises: bool = False,
        marine_payload: dict[str, Any] | None = None,
        request_raises: bool = False,
    ) -> None:
        self._api_healthy = api_healthy
        self._health_raises = health_raises
        self._marine_payload = marine_payload
        self._request_raises = request_raises

    def health(self) -> bool:
        if self._health_raises:
            raise RuntimeError("boom")
        return self._api_healthy

    def _request(self, method: str, path: str, **kwargs: Any) -> _FakeResponse:
        assert method == "GET"
        assert path == "/setup/marine/health"
        if self._request_raises:
            raise RuntimeError("connection failed")
        assert self._marine_payload is not None
        return _FakeResponse(self._marine_payload)


_FULL_B3_PAYLOAD = {
    "reachable": True,
    "error": None,
    "health": {
        "status": "degraded",
        "version": "0.2.0",
        "last_run": "2026-07-27T10:00:00Z",
        "spots": ["huntington"],
        "run_in_progress": False,
        "reasons": ["invariant_3_fired", "bathymetry stale"],
        "inputs": {
            "ww3_boundary": {"available": True, "age_s": 120},
            "wind": {"available": True, "age_s": 30},
            "bathymetry": {"available": False, "age_s": 999999},
            "tide": {"available": True, "age_s": 5},
        },
        "invariants": {
            "fired_total": 2,
            "last_fired_at": "2026-07-27T09:59:00Z",
            "last_fired_names": ["invariant_3", "invariant_8"],
        },
    },
}

_PRE_B3_PAYLOAD = {
    "reachable": True,
    "error": None,
    "health": {
        "status": "ok",
        "version": "0.1.0",
        "last_run": "2026-07-27T10:00:00Z",
        "spots": ["huntington"],
        "run_in_progress": False,
    },
}


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeApiClient | None) -> None:
    import weewx_clearskies_config.admin.routes as routes

    monkeypatch.setattr(routes, "_get_api_client", lambda: client)


@pytest.mark.parametrize("path", ["/admin/status", "/admin/status/panel"])
def test_status_full_b3_payload_renders(authed_client, monkeypatch, path):
    """Full B3 payload: status/reasons/inputs/invariants all render."""
    client = _FakeApiClient(api_healthy=True, marine_payload=_FULL_B3_PAYLOAD)
    _patch_client(monkeypatch, client)

    resp = authed_client.get(path, headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "invariant_3_fired" in body
    assert "bathymetry stale" in body
    assert "ww3_boundary" in body
    assert "wind" in body
    assert "bathymetry" in body
    assert "tide" in body
    assert "invariant_3" in body
    assert "invariant_8" in body


def test_status_pre_b3_payload_does_not_crash(authed_client, monkeypatch):
    """Load-bearing case: only the five pre-B3 keys present.

    Must render a quiet 'not reported' note for reasons/inputs/invariants,
    never a KeyError, a blank panel, or a crash.
    """
    client = _FakeApiClient(api_healthy=True, marine_payload=_PRE_B3_PAYLOAD)
    _patch_client(monkeypatch, client)

    resp = authed_client.get("/admin/status", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "not reported by this version" in body.lower()
    # Pre-B3 fields still present and rendered.
    assert "0.1.0" in body
    assert "2026-07-27T10:00:00Z" in body


@pytest.mark.parametrize(
    "error_string",
    [
        "Marine service is not configured",
        "Connection refused",
        "Connection timed out",
        "Connection failed: OSError",
        "Marine service returned HTTP 503",
        "Marine service returned a non-JSON response",
    ],
)
def test_status_marine_unreachable_shows_error_verbatim(authed_client, monkeypatch, error_string):
    """reachable=false: error string shown verbatim; page chrome + API health still render."""
    payload = {"reachable": False, "error": error_string, "health": None}
    client = _FakeApiClient(api_healthy=True, marine_payload=payload)
    _patch_client(monkeypatch, client)

    resp = authed_client.get("/admin/status", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert error_string in body
    # The page's own chrome (breadcrumb/header) still renders.
    assert "Status" in body
    # API-health section still renders.
    assert "Reachable" in body or "Not reachable" in body


def test_status_api_client_unavailable(authed_client, monkeypatch):
    """No known API / no proxy secret -- _get_api_client() returns None.

    Page must still render its own chrome without crashing.
    """
    _patch_client(monkeypatch, None)

    resp = authed_client.get("/admin/status", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "Status" in body
    assert "Cannot connect to the API" in body


def test_status_reasons_all_entries_shown_verbatim(authed_client, monkeypatch):
    """Every reasons entry appears -- not truncated, not collapsed to a count."""
    payload = {
        "reachable": True,
        "error": None,
        "health": {
            "status": "failed",
            "version": "0.2.0",
            "last_run": "2026-07-27T10:00:00Z",
            "spots": [],
            "run_in_progress": False,
            "reasons": [
                "reason_one_required_input_missing",
                "reason_two_invariant_4_fired",
                "reason_three_cycle_incomplete",
            ],
            "inputs": {},
            "invariants": {"fired_total": 0, "last_fired_at": None, "last_fired_names": []},
        },
    }
    client = _FakeApiClient(api_healthy=True, marine_payload=payload)
    _patch_client(monkeypatch, client)

    resp = authed_client.get("/admin/status", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "reason_one_required_input_missing" in body
    assert "reason_two_invariant_4_fired" in body
    assert "reason_three_cycle_incomplete" in body


def test_status_requires_session(client):
    """Unauthenticated request is rejected.

    The app's global 401 handler (app.py) converts this into an HTMX
    redirect (200 + HX-Redirect header) rather than a raw 401 -- the same
    behaviour every other _require_session route exercises (verified here
    against /admin/marine-service, an existing route with an identical
    _require_session() guard).
    """
    resp = client.get("/admin/status", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    baseline = client.get("/admin/marine-service", headers={"HX-Request": "true"})
    assert baseline.status_code == 200
    assert "HX-Redirect" in baseline.headers

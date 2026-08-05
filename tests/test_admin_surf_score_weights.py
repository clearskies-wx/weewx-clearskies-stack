"""Guard tests for the surf score weights admin section (Round S, ADR-101
guidance 6).

Regression guard only -- not evidence the live system works. Mocks
_fetch_current_config() and _get_api_client() so no real network call is
ever made; the marine service is never contacted directly (the weights flow
admin -> API /setup/apply -> marine /config, and only the API does the last
hop).

Contract under test (Round S ruling, 2026-08-05): top-level [surf_scoring]
section, keys weight_size / weight_shape / weight_conditions / weight_power
/ weight_consistency, floats > 0, sent as an all-or-nothing
payload["surf_scoring"] block on POST /setup/apply.
"""

from __future__ import annotations

from typing import Any

import pytest

_WEIGHT_KEYS = (
    "weight_size",
    "weight_shape",
    "weight_conditions",
    "weight_power",
    "weight_consistency",
)

_DEFAULTS = {
    "weight_size": "0.25",
    "weight_shape": "0.25",
    "weight_conditions": "0.20",
    "weight_power": "0.20",
    "weight_consistency": "0.10",
}

# Minimal current-config: the non-Optional ApplyRequest sections the safe
# partial-edit payload must re-send faithfully (_build_base_apply_payload).
_BASE_CONFIG: dict[str, Any] = {
    "database": {
        "kind": "mysql",
        "host": "db.example.com",
        "port": 3306,
        "user": "weewx",
        "password": "hunter2",
        "name": "weewx",
        "path": "",
    },
    "station": {
        "name": "Test Station",
        "latitude": 33.65,
        "longitude": -118.0,
        "altitude_meters": 5.0,
        "timezone": "America/Los_Angeles",
        "default_locale": "en",
    },
    "column_mapping": {"outTemp": "outTemp"},
    "column_units": {"outTemp": "degree_F"},
}


class _FakeApiClient:
    """Stand-in for ApiClient -- only .apply() is used by the weights form."""

    def __init__(self, *, apply_raises: bool = False) -> None:
        self._apply_raises = apply_raises
        self.apply_calls: list[dict[str, Any]] = []

    def apply(self, config: dict[str, Any]) -> dict[str, Any]:
        if self._apply_raises:
            raise RuntimeError("apply failed")
        self.apply_calls.append(config)
        return {"success": True}


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: dict[str, Any] | None,
    client: _FakeApiClient | None,
) -> None:
    import weewx_clearskies_config.admin.routes as routes

    monkeypatch.setattr(routes, "_fetch_current_config", lambda: config)
    monkeypatch.setattr(routes, "_get_api_client", lambda: client)


def _valid_form() -> dict[str, str]:
    return {
        "weight_size": "0.3",
        "weight_shape": "0.3",
        "weight_conditions": "0.2",
        "weight_power": "0.1",
        "weight_consistency": "0.1",
    }


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_prefills_defaults_when_section_absent(authed_client, monkeypatch):
    """No [surf_scoring] in current-config -> the ADR-101 shipped defaults
    pre-fill every input and the defaults notice renders."""
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=_FakeApiClient())

    resp = authed_client.get("/admin/surf-scoring", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    for key, default in _DEFAULTS.items():
        assert f'name="{key}"' in body
        # _format_weight trims trailing zeros: 0.20 renders as 0.2.
        assert f'value="{float(default):g}"' in body
    assert "built-in default weights" in body


def test_get_prefills_configured_values(authed_client, monkeypatch):
    """A configured [surf_scoring] section pre-fills the inputs and the
    server-rendered effective shares reflect value / sum."""
    config = dict(_BASE_CONFIG)
    config["surf_scoring"] = {
        "weight_size": "0.5",
        "weight_shape": "0.2",
        "weight_conditions": "0.1",
        "weight_power": "0.1",
        "weight_consistency": "0.1",
    }
    _patch(monkeypatch, config=config, client=_FakeApiClient())

    resp = authed_client.get("/admin/surf-scoring", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert 'value="0.5"' in body
    assert "50.0%" in body  # 0.5 / 1.0
    assert "10.0%" in body  # 0.1 / 1.0
    assert "built-in default weights" not in body


def test_get_malformed_stored_value_falls_back_per_key(authed_client, monkeypatch):
    """A stored non-positive/malformed value shows that key's default --
    mirroring the marine scorer's own per-key tolerance -- while other keys
    keep their stored values."""
    config = dict(_BASE_CONFIG)
    config["surf_scoring"] = {
        "weight_size": "-1",
        "weight_shape": "abc",
        "weight_conditions": "0.4",
        "weight_power": "0.2",
        "weight_consistency": "0.1",
    }
    _patch(monkeypatch, config=config, client=_FakeApiClient())

    resp = authed_client.get("/admin/surf-scoring", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert 'value="0.25"' in body  # size fell back to its default
    assert 'value="0.4"' in body  # conditions kept its stored value
    assert 'value="abc"' not in body  # shape fell back, never echoed


def test_get_api_unreachable_renders_notice_without_form(authed_client, monkeypatch):
    _patch(monkeypatch, config=None, client=None)

    resp = authed_client.get("/admin/surf-scoring", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.text
    assert "API unreachable" in body
    assert "surf-scoring-form" not in body


def test_get_requires_session(client, monkeypatch):
    """Unauthenticated request is rejected. The app's global 401 handler
    (app.py) converts the guard's 401 into an HTMX redirect (200 +
    HX-Redirect header) -- same behaviour as every other _require_session
    route (see test_admin_status.py)."""
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=_FakeApiClient())

    resp = client.get("/admin/surf-scoring", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers


# ---------------------------------------------------------------------------
# POST -- valid save
# ---------------------------------------------------------------------------


def test_post_valid_weights_sends_surf_scoring_block(authed_client, monkeypatch):
    """Happy path: the apply payload carries payload["surf_scoring"] with the
    five floats, rebuilt on top of the safe base payload -- and never touches
    the [marine] section."""
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)

    resp = authed_client.post(
        "/admin/surf-scoring", data=_valid_form(), headers={"HX-Request": "true"}
    )

    assert resp.status_code == 200
    assert len(fake.apply_calls) == 1
    payload = fake.apply_calls[0]
    assert payload["surf_scoring"] == {
        "weight_size": 0.3,
        "weight_shape": 0.3,
        "weight_conditions": 0.2,
        "weight_power": 0.1,
        "weight_consistency": 0.1,
    }
    # Base sections re-sent faithfully from current-config (module note on
    # the /setup/apply write path).
    assert payload["database"]["host"] == "db.example.com"
    assert payload["station"]["timezone"] == "America/Los_Angeles"
    assert payload["column_mapping"] == {"outTemp": "outTemp"}
    assert payload["column_units"] == {"outTemp": "degree_F"}
    # A weights save must never rewrite marine locations (skip-if-absent).
    assert "marine" not in payload


def test_post_valid_renders_success_result(authed_client, monkeypatch):
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)

    resp = authed_client.post(
        "/admin/surf-scoring", data=_valid_form(), headers={"HX-Request": "true"}
    )

    assert resp.status_code == 200
    assert "Surf Score Weights" in resp.text


# ---------------------------------------------------------------------------
# POST -- rejection (ADR-101 guidance 6: reject zero/negative/malformed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    ["0", "0.0", "-0.25", "abc", "", "nan", "inf", "-inf"],
    ids=["zero", "zero-float", "negative", "non-numeric", "missing", "nan", "inf", "neg-inf"],
)
def test_post_rejects_invalid_weight(authed_client, monkeypatch, bad_value):
    """Each invalid shape 422s, re-renders the form with a field error, and
    never calls /setup/apply."""
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)
    form = _valid_form()
    form["weight_power"] = bad_value

    resp = authed_client.post(
        "/admin/surf-scoring", data=form, headers={"HX-Request": "true"}
    )

    assert resp.status_code == 422
    assert fake.apply_calls == []
    body = resp.text
    assert "Enter a positive number." in body
    assert "Nothing was saved." in body
    # The offending field is marked for assistive tech.
    assert 'aria-invalid="true"' in body


def test_post_rejects_all_missing_fields(authed_client, monkeypatch):
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)

    resp = authed_client.post(
        "/admin/surf-scoring", data={}, headers={"HX-Request": "true"}
    )

    assert resp.status_code == 422
    assert fake.apply_calls == []


def test_post_valid_values_preserved_on_error_rerender(authed_client, monkeypatch):
    """An error re-render echoes the operator's still-valid entries so one
    typo doesn't wipe the other four fields."""
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)
    form = _valid_form()
    form["weight_size"] = "not-a-number"

    resp = authed_client.post(
        "/admin/surf-scoring", data=form, headers={"HX-Request": "true"}
    )

    assert resp.status_code == 422
    assert 'value="0.3"' in resp.text  # shape kept


# ---------------------------------------------------------------------------
# POST -- API failures
# ---------------------------------------------------------------------------


def test_post_api_unreachable_renders_error(authed_client, monkeypatch):
    _patch(monkeypatch, config=None, client=None)

    resp = authed_client.post(
        "/admin/surf-scoring", data=_valid_form(), headers={"HX-Request": "true"}
    )

    assert resp.status_code == 500
    assert "Cannot connect to API" in resp.text


def test_post_apply_error_renders_error(authed_client, monkeypatch):
    fake = _FakeApiClient(apply_raises=True)
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)

    resp = authed_client.post(
        "/admin/surf-scoring", data=_valid_form(), headers={"HX-Request": "true"}
    )

    assert resp.status_code == 500
    assert "API error" in resp.text


def test_post_requires_session(client, monkeypatch):
    """Unauthenticated save never reaches /setup/apply -- the 401 guard
    fires before validation, and the global handler turns it into an HTMX
    redirect (200 + HX-Redirect)."""
    fake = _FakeApiClient()
    _patch(monkeypatch, config=dict(_BASE_CONFIG), client=fake)

    resp = client.post(
        "/admin/surf-scoring", data=_valid_form(), headers={"HX-Request": "true"}
    )

    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers
    assert fake.apply_calls == []


# ---------------------------------------------------------------------------
# Help panel
# ---------------------------------------------------------------------------


def test_help_fragment_resolves_surf_scoring_keys(authed_client):
    """help.admin.surf_scoring.* keys resolve -- a missing key would echo the
    raw key text back (i18n fallback), which this asserts against."""
    resp = authed_client.get("/admin/help/surf_scoring")

    assert resp.status_code == 200
    body = resp.text
    assert "Surf Score Weights" in body
    assert "help.admin.surf_scoring" not in body

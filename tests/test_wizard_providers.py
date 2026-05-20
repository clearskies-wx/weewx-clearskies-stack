"""Tests for weewx_clearskies_config.wizard.providers — registry and connectivity.

test_provider() makes real HTTP calls; those are mocked with respx so the
test suite runs offline and deterministically.
"""

from __future__ import annotations

import pytest
import respx
import httpx

from weewx_clearskies_config.wizard.providers import (
    PROVIDERS,
    ProviderInfo,
    get_provider,
    providers_by_domain,
    recommend_providers,
    test_provider as check_provider,
)


# ---------------------------------------------------------------------------
# providers_by_domain
# ---------------------------------------------------------------------------


def test_providers_by_domain_returns_all_five_domains():
    grouped = providers_by_domain()
    assert set(grouped.keys()) == {"forecast", "alerts", "aqi", "earthquakes", "radar"}


def test_providers_by_domain_forecast_contains_nws_and_openmeteo():
    grouped = providers_by_domain()
    forecast_ids = [p.provider_id for p in grouped["forecast"]]
    assert "nws" in forecast_ids
    assert "openmeteo" in forecast_ids


def test_providers_by_domain_each_provider_appears_in_exactly_one_domain():
    grouped = providers_by_domain()
    all_ids = [p.provider_id for providers in grouped.values() for p in providers]
    assert len(all_ids) == len(set(all_ids)), "Provider IDs must be unique across domains"


def test_providers_by_domain_preserves_all_providers():
    grouped = providers_by_domain()
    total = sum(len(v) for v in grouped.values())
    assert total == len(PROVIDERS)


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


def test_get_provider_returns_provider_info_for_known_id():
    info = get_provider("nws")
    assert info is not None
    assert info.provider_id == "nws"


def test_get_provider_returns_none_for_unknown_id():
    assert get_provider("no_such_provider_xyz") is None


# ---------------------------------------------------------------------------
# recommend_providers
# ---------------------------------------------------------------------------


def test_recommend_providers_returns_nws_for_us_coordinates():
    # Washington DC
    recs = recommend_providers(38.8894, -77.0352)
    assert recs["forecast"] == "nws"


def test_recommend_providers_returns_openmeteo_for_non_us_coordinates():
    # Berlin, Germany
    recs = recommend_providers(52.52, 13.40)
    assert recs["forecast"] == "openmeteo"


def test_recommend_providers_covers_all_five_domains():
    recs = recommend_providers(38.8894, -77.0352)
    assert set(recs.keys()) == {"forecast", "alerts", "aqi", "earthquakes", "radar"}


def test_recommend_providers_us_boundary_coordinates_return_nws():
    # Near the US boundary: lat=24, lon=-130
    recs = recommend_providers(24.0, -130.0)
    assert recs["forecast"] == "nws"


def test_recommend_providers_non_us_boundary_coordinates_return_openmeteo():
    # Just outside US west boundary
    recs = recommend_providers(38.0, -131.0)
    assert recs["forecast"] == "openmeteo"


# ---------------------------------------------------------------------------
# test_provider — mocked HTTP
# ---------------------------------------------------------------------------


@respx.mock
def test_provider_returns_success_on_http_200():
    nws = get_provider("nws")
    assert nws is not None
    respx.get(nws.test_url).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    result = check_provider(nws, {})
    assert result["success"] is True
    assert "response_time_ms" in result


@respx.mock
def test_provider_returns_failure_on_http_500():
    openmeteo = get_provider("openmeteo")
    assert openmeteo is not None
    respx.get(openmeteo.test_url).mock(return_value=httpx.Response(500))
    result = check_provider(openmeteo, {})
    assert result["success"] is False
    assert result["status_code"] == 500


@respx.mock
def test_provider_returns_failure_on_http_401():
    owm = get_provider("openweathermap")
    assert owm is not None
    # Substitute a placeholder key so URL matches
    test_url = owm.test_url.replace("{api_key}", "fake_key")
    respx.get(test_url).mock(return_value=httpx.Response(401))
    result = check_provider(owm, {"api_key": "fake_key"})
    assert result["success"] is False
    assert result["status_code"] == 401


@respx.mock
def test_provider_substitutes_credentials_into_test_url():
    """Credential placeholders must be replaced before the HTTP request is made."""
    owm = get_provider("openweathermap")
    assert owm is not None
    # The mocked route only matches if the key was substituted correctly
    expected_url = owm.test_url.replace("{api_key}", "my_secret_key")
    respx.get(expected_url).mock(return_value=httpx.Response(200, json={}))
    result = check_provider(owm, {"api_key": "my_secret_key"})
    assert result["success"] is True


@respx.mock
def test_provider_url_encodes_special_chars_in_api_key():
    """API key containing '&' must be percent-encoded so it doesn't break query string."""
    iqair = get_provider("iqair")
    assert iqair is not None
    raw_key = "key&with&ampersands"
    import urllib.parse
    encoded_key = urllib.parse.quote(raw_key, safe="")
    expected_url = iqair.test_url.replace("{api_key}", encoded_key)
    respx.get(expected_url).mock(return_value=httpx.Response(200, json={}))
    result = check_provider(iqair, {"api_key": raw_key})
    assert result["success"] is True


@respx.mock
def test_provider_returns_failure_with_error_key_on_http_error():
    usgs = get_provider("usgs")
    assert usgs is not None
    respx.get(usgs.test_url).mock(return_value=httpx.Response(503))
    result = check_provider(usgs, {})
    assert result["success"] is False
    assert "error" in result


@respx.mock
def test_provider_returns_failure_on_timeout(monkeypatch):
    nws = get_provider("nws")
    assert nws is not None
    respx.get(nws.test_url).mock(side_effect=httpx.TimeoutException("timed out"))
    result = check_provider(nws, {})
    assert result["success"] is False
    assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()


@respx.mock
def test_provider_returns_failure_on_connection_error():
    rainviewer = get_provider("rainviewer")
    assert rainviewer is not None
    respx.get(rainviewer.test_url).mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = check_provider(rainviewer, {})
    assert result["success"] is False
    assert "error" in result

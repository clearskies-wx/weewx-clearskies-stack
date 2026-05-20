"""Static provider registry and API key connectivity tests.

The config UI maintains its own provider metadata — it does not import
provider modules from the API package.  This keeps the wizard usable even
before the API's runtime dependencies are fully installed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for one external data provider."""

    provider_id: str
    display_name: str
    domain: str  # forecast | alerts | aqi | earthquakes | radar
    geographic_coverage: str  # "US only", "Global", etc.
    auth_fields: tuple[str, ...]  # credential field names the operator must provide
    test_url: str  # URL to hit for the connectivity test
    test_method: str  # "get"
    notes: str = ""


PROVIDERS: list[ProviderInfo] = [
    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------
    ProviderInfo(
        "nws",
        "National Weather Service",
        "forecast",
        "US only",
        (),
        "https://api.weather.gov/points/38.8894,-77.0352",
        "get",
        "Keyless; uses User-Agent header",
    ),
    ProviderInfo(
        "openmeteo",
        "Open-Meteo",
        "forecast",
        "Global",
        (),
        "https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&hourly=temperature_2m",
        "get",
        "Keyless, free tier",
    ),
    ProviderInfo(
        "openweathermap",
        "OpenWeatherMap",
        "forecast",
        "Global",
        ("api_key",),
        "https://api.openweathermap.org/data/2.5/weather?q=London&appid={api_key}",
        "get",
    ),
    ProviderInfo(
        "aeris",
        "Aeris Weather",
        "forecast",
        "Global",
        ("client_id", "client_secret"),
        "https://api.aerisapi.com/conditions/washington,dc?client_id={client_id}&client_secret={client_secret}",
        "get",
    ),
    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    ProviderInfo(
        "nws_alerts",
        "NWS Alerts",
        "alerts",
        "US only",
        (),
        "https://api.weather.gov/alerts/active?limit=1",
        "get",
        "Keyless",
    ),
    # ------------------------------------------------------------------
    # AQI
    # ------------------------------------------------------------------
    ProviderInfo(
        "iqair",
        "IQAir / AirVisual",
        "aqi",
        "Global",
        ("api_key",),
        "https://api.airvisual.com/v2/nearest_city?lat=0&lon=0&key={api_key}",
        "get",
    ),
    ProviderInfo(
        "openweathermap_aqi",
        "OpenWeatherMap AQI",
        "aqi",
        "Global",
        ("api_key",),
        "https://api.openweathermap.org/data/2.5/air_pollution?lat=0&lon=0&appid={api_key}",
        "get",
    ),
    # ------------------------------------------------------------------
    # Earthquakes
    # ------------------------------------------------------------------
    ProviderInfo(
        "usgs",
        "USGS Earthquakes",
        "earthquakes",
        "Global",
        (),
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1",
        "get",
        "Keyless",
    ),
    # ------------------------------------------------------------------
    # Radar
    # ------------------------------------------------------------------
    ProviderInfo(
        "rainviewer",
        "RainViewer",
        "radar",
        "Global",
        (),
        "https://api.rainviewer.com/public/weather-maps.json",
        "get",
        "Keyless",
    ),
]


def providers_by_domain() -> dict[str, list[ProviderInfo]]:
    """Return PROVIDERS grouped by domain."""
    result: dict[str, list[ProviderInfo]] = {}
    for provider in PROVIDERS:
        result.setdefault(provider.domain, []).append(provider)
    return result


def recommend_providers(latitude: float, longitude: float) -> dict[str, str]:
    """Return a recommended provider_id per domain based on the operator's location.

    US locations (approximately longitude between -130 and -60, latitude
    between 24 and 50) prefer NWS for forecast and alerts.  All other
    locations prefer Open-Meteo for forecast.  Keyless defaults are used
    for AQI, earthquakes, and radar.
    """
    in_us = (-130.0 <= longitude <= -60.0) and (24.0 <= latitude <= 50.0)
    return {
        "forecast": "nws" if in_us else "openmeteo",
        "alerts": "nws_alerts" if in_us else "nws_alerts",  # only one option
        "aqi": "openweathermap_aqi",  # free tier requires key but has global coverage
        "earthquakes": "usgs",
        "radar": "rainviewer",
    }


def get_provider(provider_id: str) -> ProviderInfo | None:
    """Return the ProviderInfo for *provider_id*, or None if not found."""
    for provider in PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    return None


def test_provider(
    provider: ProviderInfo,
    credentials: dict[str, str],
) -> dict[str, Any]:
    """Make an HTTP GET to the provider's test URL with credential substitution.

    Credentials are substituted into ``{field_name}`` placeholders in
    ``provider.test_url`` before the request.

    Returns ``{"success": True, "response_time_ms": NNN}`` on HTTP 2xx or
    ``{"success": False, "error": "...", "status_code": NNN}`` on failure.
    Uses a 5-second timeout.
    """
    import httpx

    from urllib.parse import quote

    # Substitute credential placeholders into the test URL.
    # URL-encode values to prevent query-param injection via & or other metacharacters.
    url = provider.test_url
    for field_name, value in credentials.items():
        url = url.replace(f"{{{field_name}}}", quote(value, safe=""))

    headers = {
        # NWS requires a User-Agent header; use a descriptive one.
        "User-Agent": "weewx-clearskies-config/0.1 (setup wizard connectivity test)",
    }

    start = time.monotonic()
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if response.is_success:
            return {"success": True, "response_time_ms": elapsed_ms}

        return {
            "success": False,
            "error": f"HTTP {response.status_code}",
            "status_code": response.status_code,
            "response_time_ms": elapsed_ms,
        }
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": "Request timed out after 5 seconds",
            "response_time_ms": elapsed_ms,
        }
    except httpx.RequestError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": f"Connection error: {exc}",
            "response_time_ms": elapsed_ms,
        }

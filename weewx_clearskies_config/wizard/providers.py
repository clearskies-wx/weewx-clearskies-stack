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
    signup_url: str = ""  # URL to provider's API key dashboard/signup


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
        signup_url="https://home.openweathermap.org/api_keys",
    ),
    ProviderInfo(
        "aeris",
        "Vaisala Xweather",
        "forecast",
        "Global",
        ("client_id", "client_secret"),
        "https://api.aerisapi.com/conditions/washington,dc?client_id={client_id}&client_secret={client_secret}",
        "get",
        signup_url="https://www.xweather.com/signup/",
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
    ProviderInfo(
        "aeris_alerts",
        "Vaisala Xweather Alerts",
        "alerts",
        "Global (US, Canada, Europe, UK, Japan, Australia, India, Brazil, South Africa, South Korea, Mexico)",
        ("client_id", "client_secret"),
        "https://data.api.xweather.com/alerts/38.8,-77.0?client_id={client_id}&client_secret={client_secret}",
        "get",
        notes="Requires Vaisala Xweather API key (same credentials as forecast/AQI).",
        signup_url="https://www.xweather.com/signup/",
    ),
    ProviderInfo(
        "openweathermap_alerts",
        "OpenWeatherMap Alerts",
        "alerts",
        "Global (government alerts)",
        ("api_key",),
        "https://api.openweathermap.org/data/3.0/onecall?lat={latitude}&lon={longitude}&appid={api_key}",
        "get",
        notes="Requires One Call 3.0 subscription (paid tier).",
        signup_url="https://home.openweathermap.org/api_keys",
    ),
    # ------------------------------------------------------------------
    # AQI
    # ------------------------------------------------------------------
    ProviderInfo(
        "openmeteo_aqi",
        "Open-Meteo AQI",
        "aqi",
        "Global",
        (),
        "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=0&longitude=0&current=european_aqi",
        "get",
        "Free, no API key required",
    ),
    ProviderInfo(
        "iqair",
        "IQAir / AirVisual",
        "aqi",
        "Global",
        ("api_key",),
        "https://api.airvisual.com/v2/nearest_city?lat={latitude}&lon={longitude}&key={api_key}",
        "get",
        signup_url="https://www.iqair.com/dashboard/api",
    ),
    ProviderInfo(
        "aeris_aqi",
        "Xweather AQI",
        "aqi",
        "Global",
        ("client_id", "client_secret"),
        "https://data.api.xweather.com/airquality/38.8,-77.0?client_id={client_id}&client_secret={client_secret}",
        "get",
        notes="Observed data — eligible for haze confirmation (ADR-066). Uses same Xweather credentials as forecast.",
        signup_url="https://www.xweather.com/signup/",
    ),
    ProviderInfo(
        "openweathermap_aqi",
        "OpenWeatherMap AQI (deprecated)",
        "aqi",
        "Global",
        ("api_key",),
        "https://api.openweathermap.org/data/2.5/air_pollution?lat={latitude}&lon={longitude}&appid={api_key}",
        "get",
        notes="DEPRECATED — returns SILAM model predictions, not observed data. Migrate to Aeris AQI.",
        signup_url="https://home.openweathermap.org/api_keys",
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
        "Limited: zoom 7 max, no nowcast, single color scheme (since Jan 2026)",
    ),
    ProviderInfo(
        "librewxr",
        "LibreWxR",
        "radar",
        "Global",
        (),
        "https://api.librewxr.net/public/weather-maps.json",
        "get",
        "Better quality — zoom 12, 13 color schemes, nowcast, weather alerts. Self-host recommended for production.",
    ),
]


def providers_by_domain() -> dict[str, list[ProviderInfo]]:
    """Return PROVIDERS grouped by domain."""
    result: dict[str, list[ProviderInfo]] = {}
    for provider in PROVIDERS:
        result.setdefault(provider.domain, []).append(provider)
    return result


def get_provider(provider_id: str) -> ProviderInfo | None:
    """Return the ProviderInfo for *provider_id*, or None if not found."""
    for provider in PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    return None


# Plain-English messages for common HTTP status codes returned by provider APIs.
_PROVIDER_ERROR_MAP: dict[int, str] = {
    400: "Invalid request — check that your API key format is correct",
    401: "API key rejected — check the key and try again",
    403: "Access denied — your API key may be expired or disabled",
    429: "Rate limit exceeded — try again in a few minutes",
}

# Providers that send credentials as query parameters rather than as part of
# the URL template or as a header.  The test URL for these providers must NOT
# include the key placeholder in the URL string; instead the key is appended
# as a query parameter named by the value here.
#
# IQAir / AirVisual: the correct test URL is
#   https://api.airvisual.com/v2/nearest_city?key={api_key}
# The test_url already includes ?key={api_key} in the PROVIDERS list, so the
# placeholder substitution below handles it correctly.  This dict is kept as
# an explicit record of providers whose key goes in a query param (not a
# header), so future maintainers do not accidentally move their keys to headers.
_QUERY_PARAM_KEY_PROVIDERS: dict[str, str] = {
    "iqair": "key",  # key= query parameter, not a bearer header
}


def test_provider(
    provider: ProviderInfo,
    credentials: dict[str, str],
    latitude: float | str | None = None,
    longitude: float | str | None = None,
) -> dict[str, Any]:
    """Make an HTTP GET to the provider's test URL with credential substitution.

    Credentials are substituted into ``{field_name}`` placeholders in
    ``provider.test_url`` before the request.  ``{latitude}`` and
    ``{longitude}`` are also substituted when the caller supplies coordinates
    (used by IQAir and OpenWeatherMap AQI, which require a real location to
    return a meaningful result).

    Returns ``{"success": True, "response_time_ms": NNN}`` on HTTP 2xx or
    ``{"success": False, "error": "...", "status_code": NNN}`` on failure.
    Uses a 5-second timeout.
    """
    import httpx

    from urllib.parse import quote

    # Validate that every key in credentials is a declared auth field.
    # Unexpected keys could indicate a caller mistake or an injection attempt.
    unexpected = set(credentials) - set(provider.auth_fields)
    if unexpected:
        raise ValueError(
            f"Unexpected credential fields for provider {provider.provider_id!r}: "
            f"{sorted(unexpected)}"
        )

    # Substitute latitude/longitude BEFORE credential placeholders so that a
    # maliciously-crafted API key cannot expand into a coordinate placeholder.
    lat_str = str(latitude) if latitude is not None else "0"
    lon_str = str(longitude) if longitude is not None else "0"
    url = provider.test_url.replace("{latitude}", lat_str).replace("{longitude}", lon_str)

    # Substitute credential placeholders into the test URL.
    # URL-encode values to prevent query-param injection via & or other metacharacters.
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

        status = response.status_code
        friendly = _PROVIDER_ERROR_MAP.get(
            status,
            f"Provider returned an error (code {status}). Verify your API key is correct.",
        )
        return {
            "success": False,
            "error": friendly,
            "status_code": status,
            "response_time_ms": elapsed_ms,
        }
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": "Connection timed out — check your internet connection",
            "response_time_ms": elapsed_ms,
        }
    except httpx.RequestError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": f"Connection error: {exc}",
            "response_time_ms": elapsed_ms,
        }

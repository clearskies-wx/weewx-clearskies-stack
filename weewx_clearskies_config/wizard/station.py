"""Station identity extraction from weewx.conf and the Clear Skies API.

weewx stores station metadata in [Station] in weewx.conf, not in the archive
DB table.
"""

from __future__ import annotations

from typing import Any


def station_from_api(api_host: str, api_port: int = 8765) -> dict[str, Any] | None:
    """Fetch station identity from the Clear Skies API. Returns None on failure.

    Hits http://{api_host}:{api_port}/api/v1/station with a 3-second timeout.
    On any network error, HTTP error, or parse error, returns None so the
    caller can fall through to manual entry.
    """
    import httpx

    url = f"http://{api_host}:{api_port}/api/v1/station"
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
        return None

    result: dict[str, Any] = {}

    station_name = data.get("station_name") or data.get("name")
    if station_name:
        result["station_name"] = str(station_name)

    lat = _parse_float(data.get("latitude") or data.get("lat"))
    if lat is not None:
        result["latitude"] = lat

    lon = _parse_float(data.get("longitude") or data.get("lon"))
    if lon is not None:
        result["longitude"] = lon

    # API may return altitude in meters directly, or with a unit field.
    alt = _parse_float(data.get("altitude_meters") or data.get("altitude"))
    alt_unit = str(data.get("altitude_unit", "meter")).lower()
    if alt is not None:
        if "foot" in alt_unit or "feet" in alt_unit or "ft" in alt_unit:
            alt = alt * 0.3048
        result["altitude_meters"] = alt

    tz = data.get("timezone") or data.get("time_zone")
    if tz:
        result["timezone"] = str(tz)

    return result or None


def station_from_weewx_conf(conf_path: str) -> dict[str, Any]:
    """Parse *conf_path* (weewx.conf) and extract [Station] metadata.

    Returns a dict with keys: station_name, latitude, longitude,
    altitude_meters, location.

    Raises:
        FileNotFoundError: *conf_path* does not exist.
    """
    import os

    from configobj import ConfigObj  # type: ignore[import-untyped]

    if not os.path.exists(conf_path):
        raise FileNotFoundError(f"weewx.conf not found: {conf_path}")

    cfg = ConfigObj(conf_path, file_error=True)
    station = cfg.get("Station", {})

    latitude = _parse_float(station.get("latitude"))
    longitude = _parse_float(station.get("longitude"))

    # weewx stores altitude as "NNN foot" or "NNN meter" — extract the numeric part.
    altitude_raw = station.get("altitude", "")
    altitude_meters = _parse_altitude_meters(altitude_raw)

    return {
        "station_name": station.get("station_name") or None,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_meters": altitude_meters,
        "location": station.get("location") or None,
    }


def lookup_timezone(latitude: float, longitude: float) -> str | None:
    """Return the IANA timezone name for the given coordinates.

    Uses ``timezonefinder`` if available; returns None otherwise (the operator
    must select the timezone manually).
    """
    try:
        from timezonefinder import TimezoneFinder  # type: ignore[import-untyped]

        tf = TimezoneFinder()
        result: str | None = tf.timezone_at(lat=latitude, lng=longitude)
        return result
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_float(value: Any) -> float | None:
    """Convert *value* to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_altitude_meters(raw: str) -> float | None:
    """Parse a weewx altitude string like ``"123, foot"`` or ``"37.5, meter"``.

    weewx stores altitude as ``"<value>, <unit>"`` where unit is ``foot`` or
    ``meter``.  Converts feet to meters when the unit is ``foot``.
    """
    if not raw:
        return None
    # ConfigObj may parse "50, foot" as a list ['50', 'foot'] or a string.
    if isinstance(raw, list):
        parts = [str(p).strip() for p in raw]
    else:
        raw = str(raw).strip().strip("\"'")
        parts = [p.strip() for p in raw.split(",")]
    if not parts:
        return None
    try:
        value = float(parts[0])
    except (ValueError, IndexError):
        return None

    unit = parts[1].lower() if len(parts) > 1 else "meter"
    if "foot" in unit or "feet" in unit or "ft" in unit:
        return value * 0.3048
    return value

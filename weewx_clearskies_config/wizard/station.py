"""Station identity extraction from weewx.conf.

weewx stores station metadata in [Station] in weewx.conf, not in the archive
DB table.
"""

from __future__ import annotations

from typing import Any


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

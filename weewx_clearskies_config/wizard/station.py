"""Station identity utilities for the Clear Skies wizard.

The plain HTTP fallback (station_from_api) has been removed.  The web wizard
(routes.py) now fetches station identity via the secure API channel:
ApiClient.get_station().

The weewx.conf-parsing helper that used to live here was removed (dead code —
no production caller since the CLI wizard was deleted).

lookup_timezone() is a pure coordinate-to-timezone lookup with no DB or file
dependencies and is called from the web wizard.
"""

from __future__ import annotations


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

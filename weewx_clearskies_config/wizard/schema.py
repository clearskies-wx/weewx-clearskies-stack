"""Schema processing and canonical field registry for the Clear Skies wizard.

The wizard uses this module to process API schema responses and pre-populate
the column-mapping form (step 3).  Stock columns auto-map; non-stock columns
surface with a heuristic suggestion.

The canonical field registry (CANONICAL_FIELD_GROUPS, _ALL_CANONICAL_NAMES)
lives here so routes.py can import it without a circular dependency.

Note: direct DB introspection (introspect_schema / SchemaReflector / SQLAlchemy)
has been removed.  Schema data now comes from the API via ApiClient.get_schema().
"""

from __future__ import annotations

from typing import Any

_DIAGNOSTIC_PATTERNS = ("battery", "link", "status", "signal", "check")

# Explicit mappings for common weewx extension columns whose canonical names
# don't match via substring/prefix heuristics.
_KNOWN_EXTENSION_MAPPINGS: dict[str, str] = {
    "main_pollutant": "aqiMainPollutant",
    "aqi_level": "aqiCategory",
    "aqi_location": "aqiLocation",
    "ow_aqi": "aqi",
    "ow_cloud_cover": "cloudcover",
    "ow_co": "pollutantCO",
    "ow_nh3": "nh3",
    "ow_no": "no",
    "ow_no2": "pollutantNO2",
    "ow_ozone": "pollutantO3",
    "ow_pm10": "pollutantPM10",
    "ow_pm25": "pollutantPM25",
    "ow_so2": "pollutantSO2",
    "ow_visibility": "visibility",
    "snowMoisture": "snowMoisture",
}

# ---------------------------------------------------------------------------
# Comprehensive canonical field registry — grouped for the Step 3 dropdown
#
# Source: docs/contracts/canonical-data-model.md (all entities §3.1–§3.9)
#         + weewx_clearskies_api/db/reflection.py STOCK_COLUMN_MAP
#         + §2.1 unit-group members that name canonical fields
#
# Every canonical field appears in exactly one group.
# Fields within each group are sorted alphabetically.
# ---------------------------------------------------------------------------

canonical_groups: list[tuple[str, list[str]]] = [
    (
        "Temperature",
        sorted([
            "appTemp",        # apparent / feels-like temperature
            "dewpoint",
            "dewpoint1",      # expansion-slot dewpoint
            "extraTemp1", "extraTemp2", "extraTemp3",
            "extraTemp4", "extraTemp5", "extraTemp6",
            "extraTemp7", "extraTemp8",
            "heatindex",
            "heatingTemp",    # heating system supply temperature
            "humidex",        # Canadian humidex index
            "inTemp",
            "outTemp",
            "tempMax",        # daily forecast high
            "tempMin",        # daily forecast low
            "THSW",           # Temperature-Humidity-Sun-Wind (Davis VP series)
            "windchill",
        ]),
    ),
    (
        "Humidity",
        sorted([
            "extraHumid1", "extraHumid2", "extraHumid3",
            "extraHumid4", "extraHumid5", "extraHumid6",
            "extraHumid7", "extraHumid8",
            "inHumidity",
            "outHumidity",
            "snowMoisture",   # snow moisture percentage
        ]),
    ),
    (
        "Wind",
        sorted([
            "gustdir",        # direction of peak gust
            "rms",            # root-mean-square wind speed
            "vecavg",         # vector-mean wind speed
            "vecdir",         # vector-mean wind direction
            "wind",           # scalar wind (composite)
            "windDir",
            "windGust",
            "windGustDir",
            "windGustMax",    # daily forecast peak gust
            "windgustvec",    # wind gust vector
            "windrun",        # wind run = sum(windSpeed × interval)
            "windSpeed",
            "windSpeedMax",   # daily forecast max wind speed
            "windvec",        # wind vector
        ]),
    ),
    (
        "Pressure",
        sorted([
            "altimeter",
            "altimeterRate",  # rate of change of altimeter pressure
            "barometer",
            "barometerRate",  # rate of change of barometer pressure
            "pressure",
            "pressureRate",   # rate of change of station pressure
        ]),
    ),
    (
        "Rain & Snow",
        sorted([
            "ET",             # evapotranspiration
            "hail",           # per-interval hail accumulation
            "hailRate",
            "pop",            # probability of precipitation (operator-supplied)
            "precipAmount",   # forecast precipitation accumulation
            "precipProbability",      # hourly forecast precip probability
            "precipProbabilityMax",   # daily forecast max precip probability
            "precipType",     # rain / snow / sleet / freezing-rain / hail / none
            "rain",
            "rainDur",        # duration of rainfall within interval
            "rainRate",
            "snow",
            "snowDepth",
            "snowRate",
        ]),
    ),
    (
        "Solar & UV",
        sorted([
            "cloudbase",      # estimated cloud base altitude
            "cloudCover",     # forecast cloud cover (0–100)
            "cloudcover",     # archive cloud cover (wview_extended)
            "daySunshineDur", # day-to-date cumulative sunshine duration
            "illuminance",    # light level in lux
            "maxSolarRad",    # theoretical clear-sky solar radiation
            "radiation",
            "sunshineDur",    # sunshine duration within interval
            "sunshineDurDoc", # documentation alias for sunshineDur
            "UV",
            "uvIndexMax",     # daily forecast UV index maximum
        ]),
    ),
    (
        "Air Quality (AQI)",
        sorted([
            "aqi",
            "aqiCategory",
            "aqiLocation",
            "aqiMainPollutant",
            "co",             # carbon monoxide (weewx extension)
            "co2",            # carbon dioxide (weewx extension)
            "nh3",            # ammonia (weewx extension)
            "no2",            # nitrogen dioxide (weewx extension)
            "o3",             # ozone (weewx extension)
            "pb",             # lead (weewx extension)
            "pm1_0",          # PM1.0 concentration (weewx extension)
            "pm2_5",          # PM2.5 concentration (weewx extension)
            "pm10_0",         # PM10 concentration (weewx extension)
            "pollutantCO",
            "pollutantNO2",
            "pollutantO3",
            "pollutantPM10",
            "pollutantPM25",
            "pollutantSO2",
            "so2",            # sulfur dioxide (weewx extension)
        ]),
    ),
    (
        "Soil & Leaf",
        sorted([
            "leafTemp1", "leafTemp2",
            "leafWet1", "leafWet2",
            "soilMoist1", "soilMoist2", "soilMoist3", "soilMoist4",
            "soilTemp1", "soilTemp2", "soilTemp3", "soilTemp4",
        ]),
    ),
    (
        "Lightning",
        sorted([
            "lightning_distance",
            "lightning_disturber_count",
            "lightning_noise_count",
            "lightning_strike_count",
        ]),
    ),
    (
        "System & Battery",
        sorted([
            "consBatteryVoltage",
            "heatingVoltage",
            "noise",            # sound level in dB
            "referenceVoltage",
            "rxCheckPercent",
            "supplyVoltage",
            "txBatteryStatus",  # transmitter battery status flag
        ]),
    ),
    (
        "Degree Days",
        sorted([
            "cooldeg",
            "growdeg",
            "heatdeg",
        ]),
    ),
    (
        "Forecast",
        sorted([
            "narrative",        # multi-sentence daily forecast summary
            "sunrise",
            "sunset",
            "validDate",        # daily forecast date (YYYY-MM-DD)
            "validTime",        # hourly forecast valid time (UTC ISO-8601)
            "weatherCode",      # provider weather code (WMO / OWM / etc.)
            "weatherText",      # short weather label
        ]),
    ),
    (
        "Earthquake",
        sorted([
            "alert",            # USGS PAGER alert level
            "depth",            # kilometers below surface
            "felt",             # count of 'did you feel it' reports
            "latitude",
            "longitude",
            "magnitude",
            "magnitudeType",    # mw / ml / md / mb etc.
            "mmi",              # Modified Mercalli Intensity
            "place",            # human-readable location description
            "status",           # automatic / reviewed / deleted / etc.
            "tsunami",          # tsunami flag
            "url",              # event detail page URL
        ]),
    ),
    (
        "Station Metadata",
        sorted([
            "altitude",               # above mean sea level
            "firstRecord",            # oldest archive timestamp
            "hardware",               # weewx station hardware type
            "lastRecord",             # newest archive timestamp
            "name",                   # station human-readable name
            "stationId",
            "timezone",               # IANA TZ identifier
            "timezoneOffsetMinutes",
            "unitSystem",             # US / METRIC / METRICWX
        ]),
    ),
    (
        "Archive / Meta",
        sorted([
            "interval",     # archive interval length in minutes
            "observedAt",   # AQI observation timestamp
            "timestamp",    # observation timestamp (from dateTime epoch)
            "usUnits",      # weewx unit system identifier
        ]),
    ),
]

# Flat set of all canonical field names across all groups — used for
# validation without importing the API package.
_ALL_CANONICAL_NAMES: frozenset[str] = frozenset(
    name
    for _label, fields in canonical_groups
    for name in fields
)


def process_api_schema(api_response: dict[str, Any]) -> dict[str, Any]:
    """Convert an API /setup/schema response into the shape step_schema.html expects.

    The API returns::

        {
            "columns": [
                {"name": "outTemp", "db_type": "REAL", "stock": true, "canonical": "outTemp"},
                {"name": "myCustomCol", "db_type": "REAL", "stock": false, "canonical": null},
                ...
            ]
        }

    This function separates stock from non-stock columns, applies the same
    diagnostic-pattern filter, runs suggest_canonical() on non-stock columns,
    and returns::

        {
            "stock_columns": [{"db_name": ..., "canonical": ..., "auto_mapped": True}, ...],
            "unmapped_columns": [{"db_name": ..., "suggested": ..., "confidence": ...}, ...],
            "total_columns": int,
            "stock_mapped": int,
        }

    Only columns the API flags as ``stock`` are auto-mapped.  Non-stock columns
    always appear in the unmapped list for operator review, even when the API
    returns an identity canonical name.
    """
    canonical_field_names = list(_ALL_CANONICAL_NAMES)
    try:
        from weewx_clearskies_api.db.reflection import STOCK_COLUMN_MAP  # type: ignore[import-untyped]
        canonical_field_names = list(_ALL_CANONICAL_NAMES | set(STOCK_COLUMN_MAP.values()))
    except Exception:  # noqa: BLE001
        pass

    columns: list[dict[str, Any]] = api_response.get("columns", [])

    stock_columns: list[dict[str, Any]] = []
    unmapped_columns: list[dict[str, Any]] = []

    _CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}

    # First pass: collect stock (already-mapped) columns.
    claimed: dict[str, tuple[int, str]] = {}
    for col in columns:
        name: str = col.get("name", "")
        canonical: str | None = col.get("canonical") or None
        is_stock: bool = bool(col.get("stock", False))

        if is_stock:
            effective_canonical = canonical or name
            stock_columns.append(
                {
                    "db_name": name,
                    "canonical": effective_canonical,
                    "auto_mapped": True,
                }
            )
            claimed[effective_canonical] = (99, name)

    # Second pass: process non-stock columns (need operator review).
    for col in columns:
        name = col.get("name", "")
        is_stock = bool(col.get("stock", False))

        if is_stock:
            continue  # already handled above

        lower_name = name.lower()
        if any(p in lower_name for p in _DIAGNOSTIC_PATTERNS):
            continue  # skip diagnostic/battery/status columns

        suggested, confidence = suggest_canonical(name, canonical_field_names)
        unmapped_columns.append(
            {
                "db_name": name,
                "suggested": suggested,
                "confidence": confidence,
            }
        )
        if suggested:
            rank = _CONFIDENCE_RANK.get(confidence, 0)
            prev_rank, _ = claimed.get(suggested, (-1, ""))
            if rank > prev_rank:
                claimed[suggested] = (rank, name)

    # Dedup: only the highest-confidence column keeps each suggestion.
    for col in unmapped_columns:
        if col["suggested"] and claimed.get(col["suggested"], (0, ""))[1] != col["db_name"]:
            col["suggested"] = None
            col["confidence"] = "none"

    return {
        "stock_columns": stock_columns,
        "unmapped_columns": unmapped_columns,
        "total_columns": len(stock_columns) + len(unmapped_columns),
        "stock_mapped": len(stock_columns),
    }


def suggest_canonical(
    db_column: str,
    canonical_fields: list[str],
) -> tuple[str | None, str]:
    """Heuristic: case-insensitive substring match of *db_column* against known canonical names.

    Returns ``(best_match_or_None, confidence)`` where confidence is one of:
    ``"high"`` (exact case-insensitive match), ``"medium"`` (db_column is a
    substring of a canonical name or vice versa), ``"low"`` (partial overlap),
    ``"none"`` (no match found).
    """
    lower_col = db_column.lower()

    # Known extension mapping (highest priority)
    if db_column in _KNOWN_EXTENSION_MAPPINGS:
        return _KNOWN_EXTENSION_MAPPINGS[db_column], "high"

    # Exact match (case-insensitive)
    for canonical in canonical_fields:
        if canonical.lower() == lower_col:
            return canonical, "high"

    # Substring match: db_column contained in canonical or canonical in db_column.
    # Skip for single-character column names to avoid spurious matches.
    # Note: "co" and other 2-3 char canonical names are already handled by the
    # exact-match check above, so the guard only needs to block length-1 strings.
    if len(db_column) <= 1:
        return None, "none"

    substring_matches = [
        c for c in canonical_fields
        if lower_col in c.lower() or c.lower() in lower_col
    ]
    if len(substring_matches) == 1:
        return substring_matches[0], "medium"
    if len(substring_matches) > 1:
        # Return shortest match (most specific) with medium confidence
        return min(substring_matches, key=len), "medium"

    # Partial overlap: any character-level prefix sharing
    partial_matches = [
        c for c in canonical_fields
        if _longest_common_prefix(lower_col, c.lower()) >= 3
    ]
    if partial_matches:
        best = max(partial_matches, key=lambda c: _longest_common_prefix(lower_col, c.lower()))
        return best, "low"

    return None, "none"


def _longest_common_prefix(a: str, b: str) -> int:
    """Return the length of the longest common prefix of *a* and *b*."""
    length = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            length += 1
        else:
            break
    return length


# ---------------------------------------------------------------------------
# CLI wizard path — direct DB introspection (not used by web wizard)
#
# The web wizard (routes.py) uses process_api_schema() + ApiClient.get_schema()
# instead.  introspect_schema() is retained here for the CLI wizard
# (cli_wizard.py) which runs without an established API session.
# ---------------------------------------------------------------------------


def introspect_schema(db_url: str) -> dict[str, Any]:
    """Reflect the archive table schema and classify columns.

    Uses :class:`weewx_clearskies_api.db.reflection.SchemaReflector` to
    separate stock weewx columns (auto-mapped) from non-stock columns that
    the operator must review.

    Returns a dict with:
      - ``stock_columns``: list of ``{db_name, canonical, auto_mapped}``
      - ``unmapped_columns``: list of ``{db_name, suggested, confidence}``
      - ``total_columns``: int
      - ``stock_mapped``: int

    Raises:
        RuntimeError: archive table not found or DB connection failed.
        sqlalchemy.exc.OperationalError: DB unreachable.

    Note: This function is used by the CLI wizard only.  The web wizard
    uses ApiClient.get_schema() + process_api_schema() instead.
    """
    from sqlalchemy import create_engine  # type: ignore[import-untyped]
    from weewx_clearskies_api.db.reflection import (  # type: ignore[import-untyped]
        STOCK_COLUMN_MAP,
        SchemaReflector,
    )

    engine = create_engine(db_url, connect_args={"connect_timeout": 5})
    try:
        reflector = SchemaReflector(engine)
        registry = reflector.reflect()
    finally:
        engine.dispose()

    canonical_field_names = list(_ALL_CANONICAL_NAMES | set(STOCK_COLUMN_MAP.values()))

    stock_columns = [
        {
            "db_name": info.db_name,
            "canonical": info.canonical_name,
            "auto_mapped": True,
        }
        for info in registry.stock.values()
    ]

    _CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}

    # Canonical names already claimed by stock columns.
    claimed: dict[str, tuple[int, str]] = {
        info.canonical_name: (99, info.db_name)
        for info in registry.stock.values()
    }

    unmapped_columns = []
    for info in registry.unmapped.values():
        lower_name = info.db_name.lower()
        if any(p in lower_name for p in _DIAGNOSTIC_PATTERNS):
            continue
        suggested, confidence = suggest_canonical(info.db_name, canonical_field_names)
        unmapped_columns.append(
            {
                "db_name": info.db_name,
                "suggested": suggested,
                "confidence": confidence,
            }
        )
        if suggested:
            rank = _CONFIDENCE_RANK.get(confidence, 0)
            prev_rank, _ = claimed.get(suggested, (-1, ""))
            if rank > prev_rank:
                claimed[suggested] = (rank, info.db_name)

    # Dedup: only the highest-confidence column keeps each suggestion.
    for col in unmapped_columns:
        if col["suggested"] and claimed.get(col["suggested"], (0, ""))[1] != col["db_name"]:
            col["suggested"] = None
            col["confidence"] = "none"

    return {
        "stock_columns": stock_columns,
        "unmapped_columns": unmapped_columns,
        "total_columns": len(stock_columns) + len(unmapped_columns),
        "stock_mapped": len(stock_columns),
    }

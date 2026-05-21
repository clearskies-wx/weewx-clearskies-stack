"""Schema introspection using the clearskies-api SchemaReflector.

The wizard uses this module to discover the operator's archive table columns
and pre-populate the column-mapping form (step 2).  Stock columns auto-map;
non-stock columns surface with a heuristic suggestion.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine

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
    """
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

    from weewx_clearskies_config.wizard.routes import _ALL_CANONICAL_NAMES

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
    # Skip for very short column names (≤3 chars) to avoid false positives such as
    # "co" (carbon monoxide) matching "cooldeg".
    if len(db_column) <= 3:
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

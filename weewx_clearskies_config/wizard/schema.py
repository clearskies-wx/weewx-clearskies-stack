"""Schema introspection using the clearskies-api SchemaReflector.

The wizard uses this module to discover the operator's archive table columns
and pre-populate the column-mapping form (step 2).  Stock columns auto-map;
non-stock columns surface with a heuristic suggestion.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine

_DIAGNOSTIC_PATTERNS = ("battery", "link", "status", "signal", "check")


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

    canonical_field_names = list(STOCK_COLUMN_MAP.values())

    stock_columns = [
        {
            "db_name": info.db_name,
            "canonical": info.canonical_name,
            "auto_mapped": True,
        }
        for info in registry.stock.values()
    ]

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

    # Exact match (case-insensitive)
    for canonical in canonical_fields:
        if canonical.lower() == lower_col:
            return canonical, "high"

    # Substring match: db_column contained in canonical or canonical in db_column
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

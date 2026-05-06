"""Capture a portable snapshot of a weewx archive DB.

Run this on the operator's workstation against a live production weewx DB.
Output is a directory of CSVs plus tables.json describing the schema. The
seed loader reconstructs the same logical dataset against any SQLAlchemy-
supported backend (MariaDB, SQLite).

Backend-agnostic by design: schema is reflected at capture time, so whatever
extension columns are live (per ADR-035) flow through.

Connection string and date window come from environment (.env). See
snapshot/README.md for the procedure.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Table


SNAPSHOT_DIR = Path(__file__).resolve().parent / "data"
ARCHIVE_TABLE_NAME = "archive"
DATETIME_COLUMN = "dateTime"


def _env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"environment variable {name!r} is required (see .env.example)")
    return value


def _serialize_column_type(col_type) -> str:
    return str(col_type)


def _generic_type(col_type) -> str:
    """Coarse, backend-portable classification consumed by the seed loader.

    SQLAlchemy reflects dialect-specific types (INTEGER(11), DOUBLE, etc.).
    We classify into the small set the loader recreates, so MariaDB→SQLite
    (and back) round-trips without dialect parsing.
    """
    if isinstance(col_type, Boolean):
        return "boolean"
    if isinstance(col_type, Integer):
        return "integer"
    if isinstance(col_type, (Float, Numeric)):
        return "float"
    if isinstance(col_type, DateTime):
        return "datetime"
    if isinstance(col_type, LargeBinary):
        return "binary"
    if isinstance(col_type, String):
        return "string"
    return "string"


def _emit_table(engine: Engine, table: Table, where_clauses: list, out_dir: Path) -> int:
    csv_path = out_dir / f"{table.name}.csv"
    rows_written = 0
    column_names = [c.name for c in table.columns]

    stmt = select(table)
    for clause in where_clauses:
        stmt = stmt.where(clause)
    if DATETIME_COLUMN in column_names:
        stmt = stmt.order_by(table.c[DATETIME_COLUMN].asc())

    with engine.connect() as conn, csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(column_names)
        result = conn.execution_options(stream_results=True).execute(stmt)
        for row in result:
            writer.writerow([_csv_value(v) for v in row])
            rows_written += 1
    return rows_written


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def main() -> int:
    source_url = _env("CAPTURE_SOURCE_URL")
    start_epoch = _env("CAPTURE_START_EPOCH", required=False)
    end_epoch = _env("CAPTURE_END_EPOCH", required=False)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SNAPSHOT_DIR.glob("*.csv"):
        stale.unlink()
    schema_file = SNAPSHOT_DIR / "tables.json"

    engine = create_engine(source_url, pool_pre_ping=True)
    md = MetaData()
    md.reflect(bind=engine)

    if ARCHIVE_TABLE_NAME not in md.tables:
        raise SystemExit(
            f"source DB has no {ARCHIVE_TABLE_NAME!r} table — is CAPTURE_SOURCE_URL pointing "
            "at a weewx archive DB?"
        )

    captured: dict[str, dict] = {}
    where_for = {}

    if start_epoch or end_epoch:
        archive = md.tables[ARCHIVE_TABLE_NAME]
        clauses = []
        if start_epoch:
            clauses.append(archive.c[DATETIME_COLUMN] >= int(start_epoch))
        if end_epoch:
            clauses.append(archive.c[DATETIME_COLUMN] <= int(end_epoch))
        where_for[ARCHIVE_TABLE_NAME] = clauses

    for name in sorted(md.tables):
        table = md.tables[name]
        clauses = where_for.get(name, [])
        rows = _emit_table(engine, table, clauses, SNAPSHOT_DIR)
        captured[name] = {
            "columns": [
                {
                    "name": c.name,
                    "type": _serialize_column_type(c.type),
                    "generic_type": _generic_type(c.type),
                    "nullable": bool(c.nullable),
                    "primary_key": bool(c.primary_key),
                }
                for c in table.columns
            ],
            "row_count": rows,
            "primary_key": [c.name for c in table.primary_key.columns],
        }
        print(f"  {name}: {rows} rows", file=sys.stderr)

    schema_file.write_text(
        json.dumps(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_dialect": engine.dialect.name,
                "start_epoch": start_epoch,
                "end_epoch": end_epoch,
                "tables": captured,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"snapshot written to {SNAPSHOT_DIR}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

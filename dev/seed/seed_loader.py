"""Load a captured weewx snapshot into a target backend.

Reads tables.json + per-table CSVs from $SNAPSHOT_DIR, recreates the schema
in the backend pointed at by $CLEARSKIES_DB_URL using a backend-portable type
map, and bulk-inserts the rows.

Same captured dataset → MariaDB or SQLite, same logical content. Backend
choice is per ADR-012; the loader does not assume which one.

Idempotent: drops then recreates tables on each run. Dev/test only.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine


GENERIC_TYPE_MAP = {
    "integer": Integer,
    "float": Float,
    "string": String,
    "datetime": DateTime,
    "binary": LargeBinary,
    "boolean": Boolean,
}

BATCH_SIZE = 1000


def _env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"environment variable {name!r} is required")
    return value


def _build_table(metadata: MetaData, name: str, table_spec: dict) -> Table:
    columns = []
    for col in table_spec["columns"]:
        type_cls = GENERIC_TYPE_MAP.get(col["generic_type"], Text)
        if type_cls is String:
            # PKs need a bounded length; everything else can be unbounded Text
            # (operator extension columns may carry long forecast/alert prose).
            sa_type = String(255) if col["primary_key"] else Text()
        else:
            sa_type = type_cls()
        columns.append(
            Column(
                col["name"],
                sa_type,
                nullable=col["nullable"],
                primary_key=col["primary_key"],
            )
        )
    return Table(name, metadata, *columns)


def _coerce_row(row: list[str], columns: list[dict]) -> dict:
    # Pad with empty strings if the CSV row is short (trailing-empty handling).
    if len(row) < len(columns):
        row = row + [""] * (len(columns) - len(row))
    out: dict = {}
    for value, col in zip(row, columns):
        if value == "":
            out[col["name"]] = None
            continue
        gt = col["generic_type"]
        try:
            if gt == "integer":
                out[col["name"]] = int(value)
            elif gt == "float":
                out[col["name"]] = float(value)
            elif gt == "boolean":
                out[col["name"]] = value.lower() in ("1", "true", "t", "yes")
            elif gt == "binary":
                out[col["name"]] = bytes.fromhex(value)
            else:
                out[col["name"]] = value
        except (TypeError, ValueError):
            out[col["name"]] = None
    return out


def _load_table(engine: Engine, table: Table, csv_path: Path, columns: list[dict]) -> int:
    if not csv_path.exists():
        return 0
    rows_loaded = 0
    with engine.begin() as conn, csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return 0
        col_index = {name: i for i, name in enumerate(header)}
        ordered_columns = [columns[col_index[name]] for name in header]
        batch: list[dict] = []
        for row in reader:
            batch.append(_coerce_row(row, ordered_columns))
            if len(batch) >= BATCH_SIZE:
                conn.execute(table.insert(), batch)
                rows_loaded += len(batch)
                batch.clear()
        if batch:
            conn.execute(table.insert(), batch)
            rows_loaded += len(batch)
    return rows_loaded


def main() -> int:
    db_url = _env("CLEARSKIES_DB_URL")
    snapshot_dir = Path(_env("SNAPSHOT_DIR", default="/snapshot"))
    schema_file = snapshot_dir / "tables.json"
    if not schema_file.exists():
        raise SystemExit(
            f"snapshot schema {schema_file} not found — run snapshot/capture.py first"
        )
    schema = json.loads(schema_file.read_text(encoding="utf-8"))

    engine = create_engine(db_url, pool_pre_ping=True)
    print(f"target dialect: {engine.dialect.name}", file=sys.stderr)

    metadata = MetaData()
    tables: dict[str, Table] = {}
    for name, spec in schema["tables"].items():
        tables[name] = _build_table(metadata, name, spec)

    metadata.drop_all(engine)
    metadata.create_all(engine)

    total = 0
    for name, table in tables.items():
        csv_path = snapshot_dir / f"{name}.csv"
        loaded = _load_table(engine, table, csv_path, schema["tables"][name]["columns"])
        print(f"  {name}: {loaded} rows loaded", file=sys.stderr)
        total += loaded

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM archive"))
        count = result.scalar()
    print(f"verification: archive has {count} rows", file=sys.stderr)

    if count != schema["tables"].get("archive", {}).get("row_count", 0):
        print(
            f"WARN: archive row count {count} != snapshot row count "
            f"{schema['tables']['archive']['row_count']}",
            file=sys.stderr,
        )

    print(f"seed complete — {total} rows total", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

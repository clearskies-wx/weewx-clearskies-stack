# Snapshot capture

Operator-run script that pulls a portable snapshot of a production weewx
archive DB. Output (CSVs + `tables.json`) is consumed by the seed loader to
populate dev/test backends.

## Why portable, not mysqldump

`mysqldump` produces MariaDB-specific SQL. We need the same dataset to load
into both MariaDB and SQLite at test time
([ADR-012](../../../../docs/decisions/ADR-012-database-access-pattern.md)).

Per-table CSV plus a JSON schema file is the simplest format that survives
the dialect crossing — the seed loader recreates schema from the JSON using
SQLAlchemy's generic types, then bulk-inserts the CSV rows.

Schema is **reflected** at capture time, not hardcoded. Whatever extension
columns the operator has live ([ADR-035](../../../../docs/decisions/ADR-035-user-driven-column-mapping.md))
flow through automatically.

## Prerequisites

- Python 3.11+
- Network access to the production MariaDB. From DILBERT this means an SSH
  tunnel through Ratbert to the `weewx` container (port 3306). Set up
  whichever way you prefer; the script just needs `CAPTURE_SOURCE_URL` to
  resolve.
- Write access to `dev/snapshot/data/` (gitignored).

## Procedure

1. Set up an SSH tunnel from this workstation to weewx-container:3306. Example:

   ```sh
   ssh -L 3306:weewx.lxd:3306 ratbert
   ```

2. Activate a venv with the snapshot deps:

   ```sh
   cd dev/snapshot
   python -m venv .venv
   .venv/Scripts/Activate.ps1   # PowerShell on Windows
   pip install -e .             # uses pyproject.toml
   ```

3. Set environment from `dev/.env` (or export inline). The connection string,
   the optional date window, and credentials all come from there:

   ```
   CAPTURE_SOURCE_URL=mysql+pymysql://weewx:PASSWORD@127.0.0.1:3306/weewx
   CAPTURE_START_EPOCH=1714521600   # ~30 days ago in epoch seconds, optional
   CAPTURE_END_EPOCH=               # leave empty for "up to now"
   ```

4. Run:

   ```sh
   python capture.py
   ```

5. Inspect `data/tables.json` and the per-table CSVs. The script prints row
   counts to stderr so you can sanity-check the window.

## What gets captured

Every table in the source DB. The `archive` table is the one the API reads
from; aggregation tables (`archive_day_*`) and the daily summaries also come
along so test data exercises the full read path.

## Date-window guidance

Phase 1 plan specifies a 30–60 day snapshot. weewx writes 5-min archive
records by default — 30 days ≈ 8,640 rows. CSVs stay small (≪ 50 MB),
fitting comfortably in CI cache.

If `CAPTURE_START_EPOCH`/`CAPTURE_END_EPOCH` are unset, every row in the
source is captured. Use this only for one-off explorations — large captures
balloon CI time.

## Re-capturing

The output directory is wiped on each run (CSV files only — `tables.json`
gets overwritten). Schema drift is visible in PR diff against the previous
`tables.json`; treat unexpected changes as a signal worth investigating.

## What is **not** captured

Credentials, MQTT broker state, configuration files. Only DB tables.

## Sanitization

Per the project's 2026-05-04 decision-log entry: weather observation data is
public-by-design (broadcast to CWOP), so no row-level sanitization is needed
before seeding test backends.

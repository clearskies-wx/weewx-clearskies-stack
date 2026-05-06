# Seed loader

Container that reads a captured snapshot from `/snapshot/` and loads it into
the database pointed at by `CLEARSKIES_DB_URL`.

Backend-agnostic by design — same captured data, MariaDB or SQLite, no code
changes.

## Inputs

- `/snapshot/tables.json` — schema metadata produced by `capture.py`
- `/snapshot/<table>.csv` — one CSV per table

## Environment

| Variable             | Required | Notes                                                  |
|----------------------|----------|--------------------------------------------------------|
| `CLEARSKIES_DB_URL`  | yes      | SQLAlchemy URL. Compose sets it per profile.           |
| `SNAPSHOT_DIR`       | no       | Defaults to `/snapshot`. Bind-mounted by compose.      |

## Type mapping

`generic_type` field in the schema JSON drives column construction:

| generic_type | SQLAlchemy type     | Notes                                  |
|--------------|---------------------|----------------------------------------|
| integer      | Integer             |                                        |
| float        | Float               |                                        |
| string (PK)  | String(255)         | Bounded for index compatibility.       |
| string       | Text                | Unbounded — operator extension prose.  |
| datetime     | DateTime            |                                        |
| binary       | LargeBinary         | CSV stores hex; loader decodes.        |
| boolean      | Boolean             |                                        |

Unknown types fall through to Text. Capture-time classification picks the
generic class via `isinstance` checks against `sqlalchemy.types`, so any
dialect's reflected types are mapped consistently.

## Idempotency

The loader drops then recreates tables on each run. Suitable for CI and
local re-seeding. Do not point this at a production DB.

## Self-reported verification

Output reports:

- target dialect
- per-table row count loaded
- post-load `SELECT COUNT(*) FROM archive` vs. snapshot's recorded count

CI surfaces a non-zero exit on any insert failure.

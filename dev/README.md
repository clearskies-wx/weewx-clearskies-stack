# Clear Skies — dev/test stack

Reproducible development environment for `clearskies-api` integration tests
and local SPA development. Brings up a MariaDB instance (or seeds a SQLite
file) populated from a portable snapshot of a production weewx archive.

This is dev/test infrastructure, not a distributed artifact. It lives inside
`weewx-clearskies-stack` because it ships with the easy-button install repo,
but operators don't run it directly — they use `docker-compose.prod.yml`
when that lands in Phase 4.

## Why two backends

[ADR-012](../../../docs/decisions/ADR-012-database-access-pattern.md) commits
to supporting both SQLite (default weewx) and MariaDB at runtime. The CI
matrix runs every integration test against both, so we have to populate both
from the same logical dataset.

The seed loader is backend-agnostic by design — same captured snapshot, same
test data, two backends.

## Layout

```
dev/
├── docker-compose.yml        # MariaDB service + two seed-runner profiles
├── .env.example              # copy to .env and fill in
├── mariadb-init/             # MariaDB one-time init scripts (run on first start)
│   └── 01-clearskies-ro.sql  # creates clearskies_ro SELECT-only user (ADR-012)
├── snapshot/
│   ├── capture.py            # operator-run, host-side; produces a snapshot
│   └── data/                 # tables.json + per-table CSVs (gitignored for
│                             #   production captures; committed for dev seed)
└── seed/
    ├── seed_loader.py        # runs inside the seed-* container
    ├── requirements.txt      # pinned deps (== pins per rules/coding.md §1)
    └── Dockerfile
```

## One-time setup

1. `cp .env.example .env` and fill in MariaDB passwords.
2. Capture a snapshot from production weewx (see [`snapshot/README.md`](snapshot/README.md)).

## Daily use

Bring up MariaDB and seed it:

```sh
docker compose --profile mariadb up --build --abort-on-container-exit seed-mariadb
```

After `seed-mariadb` exits cleanly, MariaDB stays up serving on
`127.0.0.1:${MARIADB_HOST_PORT:-3307}`. Tear down with `docker compose down`.

Seed a SQLite file (no MariaDB service needed):

```sh
docker compose --profile sqlite run --build --rm seed-sqlite
```

The SQLite file lives in the `sqlite_data` named volume; tests mount it
read-only into the API service container.

## CI matrix

GitHub Actions runs both backends in parallel jobs. See `.github/workflows/`
in the eventual `weewx-clearskies-api` repo (Phase 1 task: wire CI scaffolding).

## Read-only enforcement vs. seeding

[ADR-012](../../../docs/decisions/ADR-012-database-access-pattern.md) requires
the **runtime** API DB user to be SELECT-only. The seed user is a separate
concern — `MARIADB_USER` from `.env` populates the database with full
privileges; the API service connects as a different `SELECT`-only user. Tests
that exercise the read-only-enforcement startup probe must use the SELECT-only
user, not the seed user.

### clearskies_ro user (SELECT-only, for integration tests)

`mariadb-init/01-clearskies-ro.sql` runs once when the MariaDB container is
first created (Docker's `/docker-entrypoint-initdb.d/` convention). It creates:

```sql
CREATE USER IF NOT EXISTS 'clearskies_ro'@'%' IDENTIFIED BY 'clearskies_ro_test';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'%';
```

The password (`clearskies_ro_test`) is hard-coded in the init script because:
- This is dev/test infrastructure only — never runs in production.
- MariaDB init SQL cannot interpolate environment variables.
- The seed stack is loopback-bound (`127.0.0.1` only) and never publicly exposed.

Integration tests connect as `clearskies_ro` using `MARIADB_RO_PASSWORD` from
`.env` (default `clearskies_ro_test`). The writable seed user (`MARIADB_USER`)
is used only for the negative write-probe tests that must confirm the probe
correctly rejects a user with DML privileges.

**Important:** If you tear down the MariaDB data volume (`docker compose down -v`)
the init script re-runs on next `docker compose up`, recreating the user.
If you only stop/start the container without removing the volume, the user
already exists and the `IF NOT EXISTS` guard prevents errors.

## Seed data

`snapshot/data/tables.json` and `snapshot/data/archive.csv` are committed.
These are 5 rows of real production data from the `weewx` container (captured
2026-05-06) including:

- All stock weewx columns (dateTime through windSpeed).
- Extension columns added by the AirVisual plugin: `aqi`, `main_pollutant`,
  `aqi_level`, `aqi_location`.
- Extension columns added by the OpenWeather plugin: `ow_aqi`, `ow_cloud_cover`,
  `ow_co`, `ow_nh3`, `ow_no`, `ow_no2`, `ow_ozone`, `ow_pm10`, `ow_pm25`,
  `ow_so2`, `ow_visibility`.

This is the minimum needed to exercise the schema reflection registry (ADR-035)
against a realistic production schema that has both stock and non-stock columns.

The full production capture (thousands of rows, date-windowed) is still an
operator-run step — see [`snapshot/README.md`](snapshot/README.md).

## What was tested

Validated end-to-end inside `weather-dev` LXD container on ratbert (per
[rules/clearskies-process.md](../../../rules/clearskies-process.md) — Windows
workstation is editing-only):

- ✅ MariaDB profile: image built, MariaDB came up healthy, seed loaded
  3-row synthetic fixture, post-load `SELECT COUNT(*)` verified.
- ✅ SQLite profile: image built, seed loaded same fixture, post-load count
  verified.
- ❌ Capture script against production (operator action; requires SSH tunnel
  + read-grant on the production MariaDB user).

If CI ever diverges from the `weather-dev` validation, treat as fix-this-now.

## Versioning notes

- MariaDB pinned to **10.11** (LTS line). Production runs on the `weewx`
  container — verify with `lxc exec weewx -- mariadb --version` and bump the
  compose tag if production is on a newer major (10.x ↔ 11.x has dialect
  differences).
- Python 3.12 in the seed container.
- SQLAlchemy 2.x per [ADR-002](../../../docs/decisions/ADR-002-tech-stack.md).

## Related

- [ADR-012](../../../docs/decisions/ADR-012-database-access-pattern.md) — DB access pattern
- [ADR-035](../../../docs/decisions/ADR-035-user-driven-column-mapping.md) — schema reflection feeds column mapping
- [ADR-038](../../../docs/decisions/ADR-038-data-provider-module-organization.md) — providers as plugin modules
- [CLEAR-SKIES-PLAN.md](../../../docs/planning/CLEAR-SKIES-PLAN.md) — Phase 1 task table

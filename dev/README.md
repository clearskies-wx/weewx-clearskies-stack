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
├── snapshot/
│   ├── capture.py            # operator-run, host-side; produces a snapshot
│   └── data/                 # gitignored output: tables.json + per-table CSVs
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

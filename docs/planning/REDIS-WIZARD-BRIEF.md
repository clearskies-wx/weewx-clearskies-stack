# Brief: Redis cache — wizard and config admin integration

**Created:** 2026-05-23
**Drives:** ADR-027 (config wizard), stack rework (Redis now bundled)
**Status:** Draft — awaiting user review

---

## Context

Redis is now included in the weewx-host and single-host compose files as an optional cache for provider API responses. Operators enable it by uncommenting `CLEARSKIES_CACHE_URL` in `.env`. This brief covers making Redis discoverable and configurable through the setup wizard and config admin UI.

## Scope

### In scope

1. **Wizard step** — add Redis as a sub-section within the existing MQTT/pipeline step (step 5), not a full new step. Toggle: "Enable persistent cache (Redis)?" with host/port fields. Follows the same optional-component pattern as MQTT.
2. **Config writer** — write `CLEARSKIES_CACHE_URL` to `secrets.env` when enabled. No `.conf` file changes needed — Redis URL is an env var, not a config file setting.
3. **WizardState** — add `redis_enabled: bool`, `redis_url: str` fields.
4. **State merge** — add new fields to the `wizard_index()` merge block.
5. **Config admin** — Redis toggle in the services section of the admin UI (if admin UI exists by then).
6. **Template** — add Redis toggle/fields to `step_mqtt.html` (conditional section, shown regardless of MQTT mode since Redis is independent of input mode).

### Out of scope

- Redis authentication (password-protected Redis). Defer unless operator demand surfaces.
- Redis Sentinel / Cluster. Single-instance only for v0.1.
- Redis on the frontend host (no use case — API is the only Redis consumer).

## Key files

| File | Change |
|---|---|
| `wizard/state.py` | Add `redis_enabled`, `redis_url` fields |
| `wizard/routes.py` | Add Redis validation in step 5 POST; add fields to merge block |
| `wizard/config_writer.py` | Write `CLEARSKIES_CACHE_URL` to `secrets.env` when enabled |
| `templates/wizard/step_mqtt.html` | Add Redis toggle and URL field (conditional section) |

## Effort estimate

Small — 1 agent round. Pattern is identical to MQTT optional config. No new step, no new template file, no schema changes.

## Open questions

1. Should Redis be a sub-section of step 5 (pipeline/caching) or its own step? Sub-section is lighter but groups unrelated concerns (MQTT input + Redis cache).
2. Should the wizard auto-detect whether Redis is reachable and pre-fill the URL?

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-23 | Redis bundled in compose stack | User directive: "Nothing is optional if it is not packaged." |
| 2026-05-23 | Wizard integration deferred to separate brief | Wizard is Phase 2 scope; compose/config changes shipped immediately. |

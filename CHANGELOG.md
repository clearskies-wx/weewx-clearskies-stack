# Changelog

All notable changes to weewx-clearskies-stack are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Pre-1.0: minor version bumps may include breaking changes. Read this file before upgrading.

**Cross-repo compatibility matrix** — which api/dashboard/realtime versions work together — is in [README.md](README.md).

---

## [0.1.0] — 2026-05-19

First public release.

### Added

**Docker Compose stack**

- `docker-compose.yaml` — clearskies-api, clearskies-realtime, clearskies-dashboard, and Caddy reverse proxy as a single `docker compose up -d` command
- `.env.example` with all configurable variables documented
- Automatic Let's Encrypt TLS via Caddy when `CADDY_HOST` is set to a public domain

**Documentation**

- `README.md` — architecture diagram, component table, cross-repo compatibility matrix, quick start, dev/test stack pointer
- `INSTALL.md` — single-host Docker Compose, cross-host, bare-metal/native, Raspberry Pi, update procedure, Home Assistant REST and MQTT examples, site password protection, troubleshooting guide
- `CONFIG.md` — full `.env` variable reference
- `SECURITY.md` — trust model, secrets management, TLS, network exposure, dependency auditing

**Development/test infrastructure (`dev/`)**

- MariaDB 10.11 service with seed loader (already present from Phase 1)
- Redis 7 service profile for provider response cache integration tests
- `dev/.env.example` with dev-stack variables
- `dev/mariadb-init/01-clearskies-ro.sql` — idempotent SELECT-only user creation

**Example Home Assistant configs**

- `examples/home-assistant/sensors-rest.yaml` — REST sensor definitions
- `examples/home-assistant/sensors-mqtt.yaml` — MQTT sensor definitions

### Updating (this release)

This is the first release; no upgrade steps apply.

[0.1.0]: https://github.com/inguy24/weewx-clearskies-stack/releases/tag/v0.1.0

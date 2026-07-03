# weewx-clearskies-stack

The deployment and orchestration hub for [Clear Skies](https://github.com/inguy24/weewx-clearskies-stack) — a modular, modern weather UI stack for [weewx](https://github.com/weewx/weewx).

This repo provides:

- **Per-host Docker Compose configs** for two-host and single-host deployments
- **Deployment guides** for container and bare-metal topologies
- **Example config files** for the API and realtime services
- **Example Home Assistant configs** for REST and MQTT integration
- **Cross-repo compatibility matrix**

Distributed AS-IS under [PolyForm Noncommercial 1.0.0](LICENSE).

---

## Architecture

```
                     weewx host                          front-end host
             ┌─────────────────────────┐       ┌──────────────────────────────────┐
             │                         │       │                                  │
             │  weewx (existing)       │       │  ┌──────────────────────────┐    │
             │  ├── archive DB         │       │  │  Caddy reverse proxy     │    │
             │  └── MQTT broker        │       │  │  TLS, SPA, /api proxy    │    │
             │                         │       │  └──────┬──────────┬────────┘    │
             │  ┌──────────────────┐   │       │         │          │             │
             │  │  clearskies-api  │◄──┼───────┼─────────┘          │             │
             │  │  :8765           │   │  HTTP │                    │             │
             │  └──────────────────┘   │       │  ┌─────────────────▼────────┐    │
             │                         │       │  │  clearskies-realtime     │    │
             │  MQTT ──────────────────┼───────┼──►  :8766 (SSE)             │    │
             │                         │       │  └──────────────────────────┘    │
             │                         │       │                                  │
             │                         │       │  clearskies-dashboard            │
             │                         │       │  (init: copies SPA to volume)    │
             └─────────────────────────┘       └──────────────────────────────────┘
```

- **API** reads the weewx archive DB and calls external providers (forecast, AQI, alerts, radar). Co-located with weewx for fast DB access.
- **Realtime** subscribes to the MQTT broker and bridges loop packets to an SSE stream.
- **Dashboard** is a React SPA served as static files by Caddy.
- **Caddy** terminates TLS, serves the dashboard, and proxies `/api/v1/*` to the API and `/sse` to realtime.

Single-host deployment puts all four containers on one machine. See [INSTALL.md](INSTALL.md).

---

## Repo structure

```
weewx-clearskies-stack/
├── weewx-host/                  # Two-host: API container on the weewx machine
│   ├── docker-compose.yml
│   └── .env.example
├── frontend-host/               # Two-host: dashboard + realtime + Caddy
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── .env.example
├── single-host/                 # All-in-one: all four containers
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── .env.example
├── config/                      # Example config files
│   ├── api.conf.example
│   └── realtime.conf.example
├── archive/                     # Pre-split monolithic configs (historical)
├── dev/                         # Dev stack (MariaDB + Redis for testing)
├── examples/                    # HA configs, reverse-proxy, systemd units
├── tests/                       # Wizard test suite
├── weewx_clearskies_config/     # Config wizard Python package
├── INSTALL.md                   # Full deployment guide
├── CONFIG.md                    # Environment and config reference
├── SECURITY.md                  # Trust model, secrets, vulnerability reporting
├── CHANGELOG.md                 # Release notes
└── README.md                    # This file
```

---

## Component repos

| Repo | Role | Distribution |
|---|---|---|
| [weewx-clearskies-api](https://github.com/inguy24/weewx-clearskies-api) | HTTP/JSON API + external data providers | `pip install` / Docker |
| [weewx-clearskies-realtime](https://github.com/inguy24/weewx-clearskies-realtime) | MQTT-to-SSE bridge for live conditions | `pip install` / Docker |
| [weewx-clearskies-dashboard](https://github.com/inguy24/weewx-clearskies-dashboard) | React SPA (static HTML/CSS/JS) | Pre-built bundle / Docker |
| **weewx-clearskies-stack** (this repo) | Orchestration, deployment guide, HA configs | Compose files + docs |

---

## Cross-repo compatibility matrix

| stack | api | realtime | dashboard | Notes |
|---|---|---|---|---|
| 0.1.0 | 0.1.0 | 0.1.0 | 0.1.0 | First public release |

---

## Quick start (Docker Compose — single host)

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack/single-host
cp .env.example .env
$EDITOR .env

mkdir -p config
cp ../config/api.conf.example config/api.conf
cp ../config/realtime.conf.example config/realtime.conf
$EDITOR config/api.conf config/realtime.conf

docker compose up -d
```

See [INSTALL.md](INSTALL.md) for the two-host deployment (recommended), prerequisites, database setup, and verification.

---

## Documentation

| Doc | Contents |
|---|---|
| [INSTALL.md](INSTALL.md) | Full deployment guide — two-host, single-host, bare-metal, Raspberry Pi |
| [CONFIG.md](CONFIG.md) | Environment variables and config file reference |
| [SECURITY.md](SECURITY.md) | Trust model, secrets management, vulnerability reporting |
| [CHANGELOG.md](CHANGELOG.md) | Release notes and upgrade guidance |

---

## Home Assistant integration

Example configs in `examples/home-assistant/`:

- `sensors-rest.yaml` — REST sensors for current conditions, forecast, AQI
- `sensors-mqtt.yaml` — MQTT sensors consuming weewx loop packets directly

See [INSTALL.md](INSTALL.md) §Home Assistant for details.

---

## Dev/test stack

`dev/` contains the developer/test docker-compose: MariaDB seeded with production weewx data + optional Redis. Not for production use. See [`dev/README.md`](dev/README.md).

---

## License

[PolyForm Noncommercial License 1.0.0](LICENSE)

This software is licensed for noncommercial use. See [ADDITIONAL-USES.md](ADDITIONAL-USES.md) for permitted uses and commercial licensing requirements.

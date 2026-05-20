# weewx-clearskies-stack

The deployment and orchestration hub for [Clear Skies](https://github.com/inguy24/weewx-clearskies-stack) — a modular, modern weather UI stack for [weewx](https://github.com/weewx/weewx).

This repo provides:

- **Docker Compose** configuration for the easy-button full-stack deployment
- **Deployment guides** for single-host, cross-host, and bare-metal topologies
- **Architecture diagram** showing how the components connect
- **Example Home Assistant configs** for REST sensor and MQTT integration
- **Cross-repo compatibility matrix** (below)

Distributed AS-IS under [GPL v3](LICENSE).

---

## Architecture

```
External provider APIs              weewx (existing)
(forecast, AQI, alerts,                 │
 earthquakes, radar)                    │ writes archive records
        │                               │ also publishes weewx/loop → MQTT broker
        │ HTTPS                         │   (needed for realtime service)
        │                               │
        ▼                               ▼
┌────────────────────────────┐    ┌──────────────────────────┐
│  weewx-clearskies-api      │    │  weewx-clearskies-       │
│  FastAPI / Python 3.12     │    │  realtime                │
│  SQLAlchemy 2.x            │    │  Python 3.12 / paho-mqtt │
│                            │    │                          │
│  reads weewx archive DB    │    │  MQTT → SSE bridge       │
│  calls external providers  │    │  (loop packet stream)    │
└──────────┬─────────────────┘    └──────────┬───────────────┘
           │  JSON / HTTP                    │  SSE
           │                                 │
           └──────────────┬──────────────────┘
                          ▼
          ┌────────────────────────────────────┐
          │   Reverse proxy (Caddy / Nginx /   │
          │   Apache)                          │
          │   TLS termination, routing         │
          └──────────────┬─────────────────────┘
                         │  HTTPS
                         ▼
          ┌────────────────────────────────────┐
          │   weewx-clearskies-dashboard       │
          │   React 19 SPA (static files)      │
          │   Tailwind v4 · shadcn/ui          │
          │   Recharts · Lucide                │
          └────────────────────────────────────┘
```

**weewx-clearskies ships zero weewx extensions.** All external data (forecast, AQI, alerts, earthquakes, radar) is fetched by clearskies-api's internal provider modules. No separate weewx extensions are required.

---

## Component repos

| Repo | Role | Distribution |
|---|---|---|
| [weewx-clearskies-api](https://github.com/inguy24/weewx-clearskies-api) | HTTP/JSON API + external data providers | `pip install` / Docker |
| [weewx-clearskies-realtime](https://github.com/inguy24/weewx-clearskies-realtime) | MQTT-to-SSE bridge for live current conditions | `pip install` / Docker |
| [weewx-clearskies-dashboard](https://github.com/inguy24/weewx-clearskies-dashboard) | React SPA (static HTML/CSS/JS) | Pre-built bundle / Docker |
| **weewx-clearskies-stack** (this repo) | Docker Compose, deployment guide, HA configs | Docs + compose file |

---

## Cross-repo compatibility matrix

Operators: check this table before mixing component versions. Untested combinations are operator's risk.

| stack | api | realtime | dashboard | Notes |
|---|---|---|---|---|
| 0.1.0 | 0.1.0 | 0.1.0 | 0.1.0 | First public release; all repos at v0.1.0 |

---

## Quick start (Docker Compose)

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack
cp .env.example .env
$EDITOR .env   # fill in database credentials and provider API keys

docker compose up -d
```

Open `https://your-host/` — the Clear Skies dashboard should load.

See [INSTALL.md](INSTALL.md) for the full step-by-step guide, including prerequisites, database setup, and verification steps.

---

## Documentation

| Doc | Contents |
|---|---|
| [INSTALL.md](INSTALL.md) | Full deployment guide — single-host Docker, cross-host, bare-metal, Raspberry Pi |
| [CONFIG.md](CONFIG.md) | All `.env` variables for the Docker Compose stack |
| [SECURITY.md](SECURITY.md) | Trust model, secrets management, vulnerability reporting |
| [CHANGELOG.md](CHANGELOG.md) | Release notes and upgrade guidance |

---

## Home Assistant integration

Example configs for consuming Clear Skies data in Home Assistant:

- `examples/home-assistant/sensors-rest.yaml` — REST sensor definitions for current conditions, forecast, and AQI
- `examples/home-assistant/sensors-mqtt.yaml` — MQTT sensor definitions consuming the weewx-mqtt loop topic directly

See [INSTALL.md](INSTALL.md) §Home Assistant for wiring instructions.

---

## Dev/test stack

The `dev/` subdirectory contains the developer/test docker-compose stack: a MariaDB instance seeded with a production weewx archive snapshot, plus an optional Redis service. This is development infrastructure — operators running Clear Skies in production do not use `dev/` directly. See [`dev/README.md`](dev/README.md) for details.

---

## License

[GNU General Public License v3.0](LICENSE)

Distributed AS-IS. See LICENSE for full terms.

# Configuration — weewx-clearskies-stack

## Overview

The stack uses three layers of configuration:

1. **`.env` file** — per-host environment variables for Docker Compose. Each deployment directory (`weewx-host/`, `frontend-host/`, `single-host/`) has its own `.env.example` to copy.
2. **`config/api.conf` and `config/realtime.conf`** — service config files in configobj INI format. Example files in `config/` at the repo root.
3. **`config/secrets.env`** — runtime secrets (API keys, DB password, MQTT password). Loaded as `env_file` by containers.

---

## .env variables by host

### weewx host (`weewx-host/.env`)

| Variable | Default | Description |
|---|---|---|
| `CLEARSKIES_VERSION` | `0.1.0` | Container image tag |
| `CLEARSKIES_CONFIG_DIR` | `./config` | Host directory containing `api.conf` |
| `CLEARSKIES_SECRETS_FILE` | `./config/secrets.env` | Path to secrets env file |
| `WEEWX_CONF_PATH` | `/etc/weewx/weewx.conf` | **Required** — host path to weewx.conf |
| `WEEWX_DB_PATH` | `/var/lib/weewx/weewx.sdb` | **Required (SQLite)** — host path to weewx.sdb |
| `CLEARSKIES_API_PORT` | `8765` | Port exposed to the host for cross-host access |

### Front-end host (`frontend-host/.env`)

| Variable | Default | Description |
|---|---|---|
| `CLEARSKIES_DOMAIN` | `localhost` | **Required** — domain for Caddy TLS cert |
| `CLEARSKIES_API_URL` | _(none)_ | **Required** — URL of API on weewx host (e.g. `http://192.168.x.x:8765`) |
| `CLEARSKIES_VERSION` | `0.1.0` | Container image tag |
| `CLEARSKIES_CONFIG_DIR` | `./config` | Host directory containing `realtime.conf` |
| `CLEARSKIES_SECRETS_FILE` | `./config/secrets.env` | Path to secrets env file |
| `CLEARSKIES_HTTP_PORT` | `80` | Caddy HTTP port |
| `CLEARSKIES_HTTPS_PORT` | `443` | Caddy HTTPS port |

### Single host (`single-host/.env`)

Merged superset — includes all variables from both tables above except `CLEARSKIES_API_URL` and `CLEARSKIES_API_PORT` (not needed when all services share a Docker network).

---

## secrets.env variables

These are loaded into containers via `env_file` and never appear in config files.

### Database (API container)

| Variable | Description |
|---|---|
| `WEEWX_CLEARSKIES_DB_USER` | Read-only database username (MariaDB) |
| `WEEWX_CLEARSKIES_DB_PASSWORD` | Database password |

### Provider API keys (API container)

| Variable | Provider |
|---|---|
| `WEEWX_CLEARSKIES_AERIS_CLIENT_ID` | Aeris (forecast, alerts, AQI, radar) |
| `WEEWX_CLEARSKIES_AERIS_CLIENT_SECRET` | Aeris |
| `WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID` | OpenWeatherMap |
| `WEEWX_CLEARSKIES_WUNDERGROUND_API_KEY` | Weather Underground |
| `WEEWX_CLEARSKIES_WUNDERGROUND_PWS_STATION_ID` | Weather Underground |
| `WEEWX_CLEARSKIES_IQAIR_KEY` | IQAir AQI |

### MQTT (realtime container)

| Variable | Description |
|---|---|
| `WEEWX_CLEARSKIES_MQTT_PASSWORD` | MQTT broker password. Leave empty for anonymous. |

### Cross-host auth

| Variable | Description |
|---|---|
| `WEEWX_CLEARSKIES_PROXY_SECRET` | Shared secret for `X-Clearskies-Proxy-Auth`. Generate with `openssl rand -hex 32`. |

### Cache (optional)

| Variable | Description |
|---|---|
| `CLEARSKIES_CACHE_URL` | Redis URL (e.g. `redis://127.0.0.1:6379/0`). Empty = in-process memory cache. |

### Log level

| Variable | Description |
|---|---|
| `CLEARSKIES_LOG_LEVEL` | Override log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Config files

Example configs are in the `config/` directory at the repo root:

- `config/api.conf.example` — all API settings with defaults and comments
- `config/realtime.conf.example` — all realtime settings including MQTT and direct mode

Copy these to your deployment's `config/` directory and edit:

```bash
cd weewx-host    # or frontend-host or single-host
mkdir -p config
cp ../config/api.conf.example config/api.conf
cp ../config/realtime.conf.example config/realtime.conf
```

Full option references:

- [weewx-clearskies-api CONFIG.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/CONFIG.md)
- [weewx-clearskies-realtime CONFIG.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/CONFIG.md)

---

## Upgrading configuration between releases

When a new release requires new config keys, [CHANGELOG.md](CHANGELOG.md) documents the migration. Services default missing keys gracefully where possible. When a new required key has no safe default, CHANGELOG calls out the manual edit before upgrade.

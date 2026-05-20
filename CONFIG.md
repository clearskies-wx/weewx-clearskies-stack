# Configuration — weewx-clearskies-stack

The Docker Compose stack is configured through a `.env` file in the repo root. Copy `.env.example` to `.env` and edit it before running `docker compose up`.

The individual component config files (`api.conf`, `realtime.conf`) are bind-mounted from the host at `/etc/weewx-clearskies/`. See each component's `CONFIG.md` for their full option reference.

---

## .env variables

### Caddy (reverse proxy)

| Variable | Default | Description |
|---|---|---|
| `CADDY_HOST` | `localhost` | The domain name or IP Caddy listens on and obtains a TLS certificate for. Set to your public domain (e.g. `weather.example.com`) for automatic Let's Encrypt certificates. |

### clearskies-api database

| Variable | Default | Description |
|---|---|---|
| `WEEWX_CLEARSKIES_DB_USER` | _(required)_ | Read-only database username. |
| `WEEWX_CLEARSKIES_DB_PASSWORD` | _(required)_ | Database password for `WEEWX_CLEARSKIES_DB_USER`. |

These are injected into the clearskies-api container as environment variables and read by `db/engine.py`. They never touch `api.conf`.

### clearskies-api provider credentials

All provider credentials are optional. Set the ones for the providers you configure in `api.conf`.

| Variable | Provider(s) | Description |
|---|---|---|
| `WEEWX_CLEARSKIES_AERIS_CLIENT_ID` | Aeris (forecast, alerts, AQI, radar) | Aeris client ID |
| `WEEWX_CLEARSKIES_AERIS_CLIENT_SECRET` | Aeris | Aeris client secret |
| `WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID` | OpenWeatherMap (forecast, alerts, AQI, radar) | OpenWeatherMap API key |
| `WEEWX_CLEARSKIES_WUNDERGROUND_API_KEY` | Weather Underground forecast | WU API key |
| `WEEWX_CLEARSKIES_WUNDERGROUND_PWS_STATION_ID` | Weather Underground forecast | Your PWS station ID |
| `WEEWX_CLEARSKIES_IQAIR_KEY` | IQAir AQI | IQAir API key |

### clearskies-realtime MQTT

| Variable | Default | Description |
|---|---|---|
| `WEEWX_CLEARSKIES_MQTT_PASSWORD` | _(empty)_ | MQTT broker password. Referenced by `[input.mqtt] password_env` in `realtime.conf`. Leave empty for anonymous brokers. |

### Proxy shared secret (cross-host deploys)

| Variable | Default | Description |
|---|---|---|
| `WEEWX_CLEARSKIES_PROXY_SECRET` | _(empty)_ | Shared secret for `X-Clearskies-Proxy-Auth` header. Required for cross-host deploys where the API binds to a non-loopback address. Generate with `openssl rand -hex 32`. Leave empty for single-host deploys. |

### Redis cache (optional)

| Variable | Default | Description |
|---|---|---|
| `CLEARSKIES_CACHE_URL` | _(empty, uses in-process memory)_ | Redis connection URL. `redis://127.0.0.1:6379/0` or `redis://[::1]:6379/0`. Set to enable persistent provider response caching. |

### Log level (optional)

| Variable | Default | Description |
|---|---|---|
| `CLEARSKIES_LOG_LEVEL` | _(uses config file value)_ | Override log level for all components: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

---

## Example .env

```bash
# Caddy
CADDY_HOST=weather.example.com

# Database (MariaDB)
WEEWX_CLEARSKIES_DB_USER=clearskies_ro
WEEWX_CLEARSKIES_DB_PASSWORD=<your-db-password>

# Forecast and alerts provider — Open-Meteo (keyless, no credentials needed)
# If using OpenWeatherMap:
# WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID=<your-owm-key>

# AQI provider — Open-Meteo (keyless, no credentials needed)
# If using IQAir:
# WEEWX_CLEARSKIES_IQAIR_KEY=<your-iqair-key>

# MQTT (leave empty for anonymous broker)
WEEWX_CLEARSKIES_MQTT_PASSWORD=

# Cross-host proxy secret (leave empty for single-host)
WEEWX_CLEARSKIES_PROXY_SECRET=
```

---

## api.conf and realtime.conf

These files are not managed by this repo — they are bind-mounted from `/etc/weewx-clearskies/` on the host. See:

- [weewx-clearskies-api CONFIG.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/CONFIG.md) — every api.conf section and key
- [weewx-clearskies-realtime CONFIG.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/CONFIG.md) — every realtime.conf section and key

Configuration files survive `docker compose pull` and `docker compose up -d` — they are on the host filesystem and are not modified by the image update.

---

## Upgrading configuration between releases

When a new release requires new config keys, [CHANGELOG.md](CHANGELOG.md) documents the migration. The service defaults missing keys gracefully where possible. When a new required key has no safe default, CHANGELOG calls out the manual edit before upgrade.

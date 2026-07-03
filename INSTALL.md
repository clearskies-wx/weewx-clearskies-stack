# Installation — weewx-clearskies-stack

This guide covers deploying the full Clear Skies stack. For installing individual components without Docker, see each component's own `INSTALL.md`.

---

## Install order — dependency chain

Install components in this order. Each step depends on the ones above it.

| # | Component | Install method | Why this order |
|---|-----------|---------------|----------------|
| 1 | **weewx** (5.x) | Operator's existing install | Everything depends on the weewx engine running and producing archive records |
| 2 | **ClearSkiesLoopRelay extension** | `weectl extension install <tarball>` → restart weewx | Creates the Unix socket (`/var/run/weewx-clearskies/loop.sock`) that the API reads loop packets from |
| 3 | **(Optional) ClearSkiesTruesun extension** | `weectl extension install <tarball>` + `pip install pvlib cdsapi h5netcdf` into weewx's Python environment → restart weewx | Overrides `maxSolarRad` with pvlib Simplified Solis model. Not required — weewx falls back to built-in Ryan-Stolzenbach |
| 4 | **Filesystem setup** (native only) | `sudo bash scripts/install-prerequisites.sh` | Creates `clearskies` user, `weewx-ro` group, config/runtime directories, DB permissions |
| 5 | **API** | `pip install --pre weewx-clearskies-api` (native) or `docker compose up` (Docker) | Starts in life-support mode if no `api.conf` — serves `/setup/*` endpoints for the wizard |
| 6 | **Config UI** | `pip install --pre weewx-clearskies-config` (native) or included in compose | Connects to the API's `/setup/*` endpoints. Run the wizard to generate `api.conf` and `secrets.env` |
| 7 | **Dashboard** | `npm run build` + rsync to web root (native) or init container in compose | Static SPA — needs the API running to display data |
| 8 | **Caddy** | Install + configure with provided Caddyfile example | Reverse proxy, TLS termination. Routes `/api/v1/*` and `/sse` to the API, `/wizard*` and `/admin*` to the Config UI, `/*` to dashboard static files |
| 9 | **Verify** | `curl https://your-site/api/v1/status` | Should return `{"configured": true}` after wizard completes |

For Docker compose deployments, steps 4–8 are handled by `docker compose up` — only steps 1–3 (weewx + extensions) are manual.

---

## Supported environments

| Environment | Recommended install path | Notes |
|---|---|---|
| Debian / Ubuntu (Docker) | docker-compose (this guide) | Simplest path; components in containers |
| Raspberry Pi OS | docker-compose | Docker Engine available for Pi OS (arm64/armhf) |
| LXD container (Ubuntu 24.04) | docker-compose inside container | Set `security.nesting=true` on the LXC profile |
| Proxmox VM (Ubuntu 24.04 guest) | docker-compose | Same as native Ubuntu |
| Bare-metal native | pip + systemd per component | See each component's INSTALL.md |
| Windows | Docker Desktop + docker-compose | Native Python install unsupported on Windows |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker Engine | 24+ | [Install guide](https://docs.docker.com/engine/install/) |
| Docker Compose plugin | v2.20+ | Bundled with Docker Desktop; `apt install docker-compose-plugin` on Linux |
| weewx | 5.x | Running on the host or a reachable host; archive DB accessible |
| ClearSkiesLoopRelay | weewx extension | Creates the Unix socket the API reads loop packets from. Install via `weectl extension install`. |

---

## Deployment topologies

### Two-host (default)

The recommended deployment splits the stack across two machines:

- **weewx host** — runs the API container, co-located with the weewx archive database for fast local reads.
- **Front-end host** — runs the dashboard, realtime, and Caddy containers. Caddy proxies `/api/v1/*` requests over the network to the API on the weewx host.

This topology isolates the database from internet-facing services.

### Single-host

All four containers run on one machine alongside weewx. Simpler to set up, suitable for operators who prefer a single-box deployment.

### Native (bare-metal)

Install each component with pip and manage with systemd. No Docker required.

---

## Two-host Docker Compose deployment

### weewx host setup

The weewx host runs only the API container.

#### 1. Clone the repo on the weewx host

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack/weewx-host
```

#### 2. Configure environment

```bash
cp .env.example .env
$EDITOR .env
```

Set at minimum:

- `WEEWX_CONF_PATH` — path to your `weewx.conf`
- `WEEWX_DB_PATH` — path to `weewx.sdb` (SQLite) or set to a placeholder for MariaDB

#### 3. Create config directory and api.conf

```bash
mkdir -p config
cp ../config/api.conf.example config/api.conf
$EDITOR config/api.conf
```

Key settings in `api.conf`:

- `[api] bind_host = 0.0.0.0` — required for Docker port forwarding
- `[database] kind` — `sqlite` or `mysql`
- `[database] path` — `/data/weewx.sdb` (the container-internal mount point)

For MariaDB, also set `host`, `port`, `name` in `[database]` and create a read-only database user (see below).

#### 4. Create secrets.env

```bash
cat > config/secrets.env << 'EOF'
# Database (MariaDB only)
WEEWX_CLEARSKIES_DB_USER=clearskies_ro
WEEWX_CLEARSKIES_DB_PASSWORD=changeme

# Provider API keys (optional — set for enabled providers)
# WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID=
# WEEWX_CLEARSKIES_AERIS_CLIENT_ID=
# WEEWX_CLEARSKIES_AERIS_CLIENT_SECRET=
# WEEWX_CLEARSKIES_IQAIR_KEY=
EOF
chmod 600 config/secrets.env
```

#### 5. Start the API

```bash
docker compose up -d
```

The compose file includes a Redis container for caching provider API responses. To enable it, uncomment `CLEARSKIES_CACHE_URL` in `.env`. Redis is optional — without it, the API uses in-process memory caching (cleared on restart).

#### 6. Verify

```bash
# API health check
curl http://127.0.0.1:8765/api/v1/station

# From another host (replace with weewx host IP)
curl http://192.168.x.x:8765/api/v1/station
```

### Front-end host setup

The front-end host runs the dashboard, realtime, and Caddy containers.

#### 1. Clone the repo on the front-end host

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack/frontend-host
```

#### 2. Configure environment

```bash
cp .env.example .env
$EDITOR .env
```

Set at minimum:

- `CLEARSKIES_DOMAIN` — your public domain (e.g. `weather.example.com`)
- `CLEARSKIES_API_URL` — URL of the API on the weewx host (e.g. `http://192.168.x.x:8765`)

#### 3. Create config directory and realtime.conf

```bash
mkdir -p config
cp ../config/realtime.conf.example config/realtime.conf
$EDITOR config/realtime.conf
```

Key settings in `realtime.conf`:

- `[input] mode = mqtt` — required for multi-host (weewx is on a different machine)
- `[[mqtt]] broker_host` — IP or hostname of the MQTT broker (usually the weewx host)

#### 4. Create secrets.env

```bash
cat > config/secrets.env << 'EOF'
# MQTT password (leave empty for anonymous broker)
WEEWX_CLEARSKIES_MQTT_PASSWORD=

# Proxy shared secret (optional, for cross-host API auth)
# WEEWX_CLEARSKIES_PROXY_SECRET=
EOF
chmod 600 config/secrets.env
```

#### 5. Start the front-end stack

```bash
docker compose up -d
```

#### 6. Verify

```bash
# All containers should be healthy
docker compose ps

# Dashboard should load
curl -s https://weather.example.com/ | head -5

# API proxy should work (routed to weewx host)
curl https://weather.example.com/api/v1/station

# SSE stream should be active
curl -N https://weather.example.com/sse
```

### MariaDB read-only user (if applicable)

If weewx uses MariaDB, create a SELECT-only user for the API:

```sql
CREATE USER IF NOT EXISTS 'clearskies_ro'@'%' IDENTIFIED BY '<password>';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'%';
FLUSH PRIVILEGES;
```

For tighter access control, replace `%` with the Docker bridge network range (typically `172.16.0.0/12` for single-host, or the specific container/host IP for cross-host).

---

## Single-host Docker Compose deployment

All four services on one machine alongside weewx.

### 1. Clone and configure

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack/single-host
cp .env.example .env
$EDITOR .env
```

### 2. Create config files

```bash
mkdir -p config
cp ../config/api.conf.example config/api.conf
cp ../config/realtime.conf.example config/realtime.conf
$EDITOR config/api.conf
$EDITOR config/realtime.conf
```

For single-host, set `[input] mode = direct` in `realtime.conf` if using the Unix socket, or `mode = mqtt` if weewx-mqtt is publishing.

### 3. Create secrets.env

```bash
cat > config/secrets.env << 'EOF'
WEEWX_CLEARSKIES_DB_USER=clearskies_ro
WEEWX_CLEARSKIES_DB_PASSWORD=changeme
WEEWX_CLEARSKIES_MQTT_PASSWORD=
EOF
chmod 600 config/secrets.env
```

### 4. Start the stack

```bash
docker compose up -d
```

The compose file includes a Redis container for caching provider API responses. To enable it, uncomment `CLEARSKIES_CACHE_URL` in `.env`. Redis is optional — without it, the API uses in-process memory caching (cleared on restart).

### 5. Verify

```bash
docker compose ps
curl https://weather.example.com/api/v1/station
```

---

## Bare-metal (native) deployment

Install each component with pip and manage with systemd:

- [weewx-clearskies-api INSTALL.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/INSTALL.md)
- [weewx-clearskies-realtime INSTALL.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/INSTALL.md)
- [weewx-clearskies-dashboard INSTALL.md](https://github.com/inguy24/weewx-clearskies-dashboard/blob/main/INSTALL.md)

Configure your existing reverse proxy (Apache, Nginx, or Caddy) to serve dashboard static files and proxy `/api/v1/*` and `/sse` to the respective services. Example configs are in `examples/reverse-proxy/`.

---

## Raspberry Pi

Pi OS supports Docker Engine (arm64 and armhf). The Docker Compose path works as-is on a Pi 4 or Pi 5 with 4 GB+ RAM. The native pip path also works with Python 3.12 (available via deadsnakes PPA on Pi OS Bookworm).

The Skyfield ephemeris computation for almanac data runs comfortably on a Pi 4. The first run downloads `de421.bsp` (~17 MB); subsequent runs use the cache.

---

## Updating

**Docker Compose:**

```bash
docker compose pull
docker compose up -d
```

Config files in `config/` are on the host filesystem and preserved across image updates.

**Native (pip):**

```bash
pip install -U weewx-clearskies-api
pip install -U weewx-clearskies-realtime
sudo systemctl restart weewx-clearskies-api weewx-clearskies-realtime
```

Read [CHANGELOG.md](CHANGELOG.md) before upgrading.

---

## Protecting your site with a password

Clear Skies has no built-in authentication. To require a password, add it at the reverse proxy layer.

**Caddy basic auth:**

```caddy
weather.example.com {
    basicauth {
        <username> <bcrypt-hash>
    }
    # ... rest of config
}
```

Generate a bcrypt hash: `caddy hash-password`

For richer access control, see [Authelia](https://www.authelia.com/) or [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/).

---

## Home Assistant integration

### REST sensors

```yaml
sensor:
  - platform: rest
    name: "Outdoor Temperature"
    resource: "http://192.0.2.5:8765/api/v1/current"
    value_template: "{{ value_json.data.outTemp }}"
    unit_of_measurement: "°F"
    scan_interval: 300
```

Replace `192.0.2.5` with your clearskies-api host IP.

### MQTT sensors

```yaml
sensor:
  - platform: mqtt
    name: "Outdoor Temperature (live)"
    state_topic: "weewx/loop"
    value_template: "{{ value_json.outTemp }}"
    unit_of_measurement: "°F"
```

See `examples/home-assistant/` for complete configs.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard loads but shows no data | API not reachable | Check `/api/v1/station`; verify `CLEARSKIES_API_URL` in front-end `.env` |
| No real-time updates | Realtime not running or SSE not proxied | Check port 8082 health; confirm MQTT connection |
| `FATAL: write-probe succeeded` | DB user has write access | Re-create user with SELECT-only grant |
| Skyfield download fails | No internet from container | Pre-download `de421.bsp` to ephemeris directory |
| Forecast / AQI shows no data | Provider not configured | Set provider in `api.conf`; add API key to `secrets.env` |

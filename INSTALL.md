# Installation — weewx-clearskies-stack

This guide covers deploying the full Clear Skies stack. For installing individual components without Docker, see each component's own `INSTALL.md`.

---

## Supported environments

| Environment | Recommended install path | Notes |
|---|---|---|
| Debian / Ubuntu (Docker) | docker-compose (this guide) | Simplest path; all components in containers |
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
| MQTT broker | Any MQTT 3.1.1 broker | For live current conditions (SSE). EMQX or Mosquitto. If weewx-mqtt is not running, the realtime service will not publish events but the dashboard still works. |

---

## Single-host Docker Compose deployment

This is the recommended path for most operators: all four components (api, realtime, dashboard, Caddy reverse proxy) running on the same host as weewx.

### 1. Clone the repo

```bash
git clone https://github.com/inguy24/weewx-clearskies-stack.git
cd weewx-clearskies-stack
```

### 2. Copy and edit the environment file

```bash
cp .env.example .env
$EDITOR .env
```

Fill in at minimum:

- `WEEWX_CLEARSKIES_DB_USER` and `WEEWX_CLEARSKIES_DB_PASSWORD` — read-only database credentials
- `CADDY_HOST` — your domain or hostname (e.g. `weather.example.com`)
- Any provider API keys you want to enable (forecast, AQI, etc.)

See [CONFIG.md](CONFIG.md) for the full variable reference.

### 3. Create a read-only database user (MariaDB)

If weewx uses MariaDB, create a SELECT-only user for the API service:

```sql
-- Run as the MariaDB root user
CREATE USER IF NOT EXISTS 'clearskies_ro'@'172.16.0.0/12' IDENTIFIED BY '<password>';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'172.16.0.0/12';

-- Also grant from localhost if the API container connects via the host network
CREATE USER IF NOT EXISTS 'clearskies_ro'@'127.0.0.1' IDENTIFIED BY '<password>';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'127.0.0.1';

CREATE USER IF NOT EXISTS 'clearskies_ro'@'::1' IDENTIFIED BY '<password>';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'::1';

FLUSH PRIVILEGES;
```

Set the same password in `.env` as `WEEWX_CLEARSKIES_DB_PASSWORD`.

SQLite: the `.sdb` file path must be readable by the `clearskies-api` container user. Mount it read-only in `docker-compose.yaml`.

### 4. Configure api.conf and realtime.conf

The compose stack expects operator config files at:

- `/etc/weewx-clearskies/api.conf`
- `/etc/weewx-clearskies/realtime.conf`

These are bind-mounted into the containers so they persist across image updates.

Create the directory and copy the examples from the component repos:

```bash
sudo mkdir -p /etc/weewx-clearskies
```

For `api.conf`, see [weewx-clearskies-api CONFIG.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/CONFIG.md).

For `realtime.conf`, see [weewx-clearskies-realtime CONFIG.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/CONFIG.md).

### 5. Start the stack

```bash
docker compose up -d
docker compose logs -f
```

### 6. Verify

```bash
# Caddy / HTTPS
curl https://weather.example.com/api/v1/station

# Internal health checks
curl http://127.0.0.1:8081/health/ready   # api
curl http://127.0.0.1:8082/health/ready   # realtime

# Open dashboard in browser
# https://weather.example.com/
```

---

## Cross-host deployment

For operators who run weewx on one host and the Clear Skies services on a separate host.

In this topology:
- **weewx host**: weewx, MariaDB, MQTT broker
- **dashboard host**: clearskies-api, clearskies-realtime, clearskies-dashboard, Caddy

### Additional steps for cross-host

1. **MariaDB** — create the `clearskies_ro` user with a `%` wildcard or the specific dashboard-host IP. Ensure the MariaDB port is reachable from the dashboard host (adjust firewall rules).

2. **MQTT** — configure the MQTT broker to accept connections from the dashboard host. Set appropriate ACL rules.

3. **Proxy secret** — generate a shared secret and set it on both hosts:

   On the **dashboard host** `.env`:
   ```bash
   WEEWX_CLEARSKIES_PROXY_SECRET=<openssl rand -hex 32>
   ```

   In `api.conf` on the dashboard host, set `[api] bind_host` to a non-loopback address reachable by the reverse proxy container.

4. **api.conf `[database]`** — point `host` at the weewx host's IP or hostname:
   ```ini
   [database]
   kind = mysql
   host = 192.0.2.10
   port = 3306
   name = weewx
   ```

   IPv6 is supported:
   ```ini
   host = 2001:db8::10
   ```

---

## Bare-metal (native) deployment

Install each component with pip and manage with systemd. Follow each component's own `INSTALL.md`:

- [weewx-clearskies-api INSTALL.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/INSTALL.md)
- [weewx-clearskies-realtime INSTALL.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/INSTALL.md)
- [weewx-clearskies-dashboard INSTALL.md](https://github.com/inguy24/weewx-clearskies-dashboard/blob/main/INSTALL.md)

Configure your existing Apache, Nginx, or Caddy reverse proxy to serve the dashboard static files and proxy `/api` and `/sse` to the respective services.

---

## Raspberry Pi

Pi OS is Debian-based and supports Docker Engine (arm64 and armhf). The Docker Compose path works as-is on a Pi 4 or Pi 5 with 4 GB RAM or more. The native pip path also works but requires Python 3.12 (available via deadsnakes PPA on Pi OS Bookworm).

Performance note: the Skyfield ephemeris computation for almanac data runs comfortably on a Pi 4. The first run downloads the de421.bsp file (~17 MB); subsequent runs use the cached file.

---

## Updating

**Docker Compose:**

```bash
docker compose pull
docker compose up -d
```

Configuration files at `/etc/weewx-clearskies/` are bind-mounted and preserved across image updates.

**Native (pip):**

```bash
pip install -U weewx-clearskies-api
pip install -U weewx-clearskies-realtime
# Rebuild the dashboard: git pull && npm install && npm run build
sudo systemctl restart weewx-clearskies-api weewx-clearskies-realtime
```

Read [CHANGELOG.md](CHANGELOG.md) before upgrading. It documents breaking changes and required manual steps. Check the compatibility matrix in [README.md](README.md) before mixing component versions.

---

## Protecting your site with a password

Clear Skies has no built-in user authentication — it serves public weather data. To require a password to view the site, add authentication at the reverse proxy layer.

**Caddy basic auth:**

```caddy
weather.example.com {
    basicauth {
        <username> <bcrypt-hash>
    }
    # ... rest of config
}
```

Generate a bcrypt hash with: `caddy hash-password`

**Apache `mod_auth_basic`:**

```apache
<Location />
    AuthType Basic
    AuthName "Weather Station"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user
</Location>
```

Create the password file with: `htpasswd -c /etc/apache2/.htpasswd <username>`

For richer access control (SSO, MFA), see [Authelia](https://www.authelia.com/) or [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/).

---

## Home Assistant integration

### REST sensors

Add to `configuration.yaml`:

```yaml
# examples/home-assistant/sensors-rest.yaml
sensor:
  - platform: rest
    name: "Outdoor Temperature"
    resource: "http://192.0.2.5:8765/api/v1/current"
    # IPv6 example:
    # resource: "http://[2001:db8::5]:8765/api/v1/current"
    value_template: "{{ value_json.data.outTemp }}"
    unit_of_measurement: "°F"
    scan_interval: 300

  - platform: rest
    name: "AQI"
    resource: "http://192.0.2.5:8765/api/v1/aqi/current"
    value_template: "{{ value_json.data.aqi }}"
    scan_interval: 600
```

Replace `192.0.2.5` with your clearskies-api host IP. In a single-host deploy, use `127.0.0.1` or the loopback address.

### MQTT sensors

If weewx-mqtt is publishing loop packets to your broker, Home Assistant can consume them directly without going through clearskies-api:

```yaml
# examples/home-assistant/sensors-mqtt.yaml
sensor:
  - platform: mqtt
    name: "Outdoor Temperature (live)"
    state_topic: "weewx/loop"
    value_template: "{{ value_json.outTemp }}"
    unit_of_measurement: "°F"
```

MQTT sensors update with every weewx loop cycle (typically every 2 seconds), whereas REST sensors poll the API.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard loads but shows no data | clearskies-api not reachable | Check `/api/v1/station` directly; confirm reverse proxy routes `/api/` correctly |
| No real-time updates in browser | clearskies-realtime not running, or SSE not proxied | Check `/health/ready` on port 8082; confirm `proxy_buffering off` in Nginx |
| `FATAL: write-probe succeeded` | DB user has write access | Re-create the DB user with SELECT-only grant |
| Skyfield download fails on first start | No internet access from container | Pre-download `de421.bsp` and place in the bind-mounted ephemeris directory |
| Forecast / AQI shows no data | Provider not configured | Set the provider in `api.conf`; confirm API key is in `.env` |

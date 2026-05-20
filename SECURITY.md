# Security — weewx-clearskies-stack

This repository is part of [Clear Skies](https://github.com/inguy24/weewx-clearskies-stack), distributed AS-IS under [GPL v3](LICENSE). There is no support window, no LTS, and no security backport policy — only the current release is available.

---

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:

**Security tab → Advisories → "Report a vulnerability"**

Or open a GitHub issue prefixed with `[security]` if private reporting is unavailable.

---

## Trust model

Clear Skies is a **read-only weather data stack**. It displays public environmental data. There are no user accounts, no write operations to the database, and no payment or health data.

The security model is inherited from the three component services:

- **clearskies-api** — enforces a read-only database user at startup; inputs validated by Pydantic; secrets in environment variables; JSON logs with credential redaction.
- **clearskies-realtime** — MQTT password from environment variable; SSE stream carries only public weather data.
- **clearskies-dashboard** — static SPA with no server-side secrets.

For component-specific security details, see:

- [weewx-clearskies-api SECURITY.md](https://github.com/inguy24/weewx-clearskies-api/blob/main/SECURITY.md)
- [weewx-clearskies-realtime SECURITY.md](https://github.com/inguy24/weewx-clearskies-realtime/blob/main/SECURITY.md)
- [weewx-clearskies-dashboard SECURITY.md](https://github.com/inguy24/weewx-clearskies-dashboard/blob/main/SECURITY.md)

---

## Secrets management in the Docker Compose stack

All secrets are passed to containers via environment variables. The `.env` file is gitignored and must not be committed to version control.

**Mode-0600 recommendation:** restrict the `.env` file to the owner:

```bash
chmod 0600 .env
```

**Secret checklist:**
- Database password: `WEEWX_CLEARSKIES_DB_PASSWORD`
- Provider API keys: `WEEWX_CLEARSKIES_AERIS_*`, `WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID`, etc.
- MQTT password: `WEEWX_CLEARSKIES_MQTT_PASSWORD`
- Proxy shared secret: `WEEWX_CLEARSKIES_PROXY_SECRET` (cross-host deploys only)

None of these should appear in `api.conf`, `realtime.conf`, or any committed config file. Both config loaders include a secret-leak guard that rejects any INI key matching `_(KEY|SECRET|TOKEN|PASSWORD)$`.

---

## TLS

The Caddy reverse proxy in the Docker Compose stack handles TLS automatically via Let's Encrypt when `CADDY_HOST` is set to a public domain name. For internal/self-signed scenarios, configure Caddy with a local certificate.

For bare-metal deployments, use certbot with the Nginx or Apache plugin.

**Always run HTTPS in production.** HTTP exposes the weather data (which is public) but more importantly exposes any authentication headers (the proxy secret and MQTT password) in plaintext.

---

## Network exposure

The default Docker Compose configuration exposes only port 80 and 443 (Caddy) to the host network. The API, realtime, and health check ports are container-internal and not exposed to the host.

For single-host bare-metal deployments:
- `clearskies-api` binds to `127.0.0.1:8765` and `::1:8765` (loopback only).
- `clearskies-realtime` binds to `0.0.0.0:8766` by default; restrict to `127.0.0.1` for single-host deploys.
- Health check ports (`8081`, `8082`) are loopback-only.

---

## Dependency auditing

The CI pipeline runs `gitleaks` on every PR and push to detect accidentally committed secrets. The component repos run `pip-audit` and `npm audit` for dependency vulnerability scanning.

---

## Protecting access to the dashboard

Clear Skies has no built-in user authentication. To require a password, add it at the reverse proxy layer. See [INSTALL.md](INSTALL.md) §Protecting your site with a password for Caddy and Apache examples, and pointers to Authelia and Cloudflare Access.

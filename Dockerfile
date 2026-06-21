# Expected volume mounts:
#   /etc/weewx-clearskies/          config dir shared with the API container
#   /srv/dashboard:ro               dashboard build output (card-manifest.json for layout editor)

# ── builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Build context must be the repos parent (contains both weewx-clearskies-stack/
# and weewx-clearskies-api/).  Compose sets dockerfile: to point here.
COPY weewx-clearskies-stack/pyproject.toml .
COPY weewx-clearskies-stack/README.md .
COPY weewx-clearskies-stack/weewx_clearskies_config/ weewx_clearskies_config/

# weewx-clearskies-api is not on PyPI; install from sibling repo first.
COPY weewx-clearskies-api/ /api-src/
RUN pip install --no-cache-dir /api-src && pip install --no-cache-dir .

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# Copy only the installed package artifacts; leave build tools behind.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/weewx-clearskies-config /usr/local/bin/weewx-clearskies-config

# System user — no home directory, no login shell, fixed UID for bind-mount
# permission alignment on the host side.
RUN useradd --system --uid 1000 --no-create-home --shell /usr/sbin/nologin clearskies

USER clearskies

EXPOSE 9876

# urllib.request is stdlib — no extra deps, no curl/wget required in the image.
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9876/health')"

ENTRYPOINT ["python", "-m", "weewx_clearskies_config"]
# Caddy handles TLS termination; bind all interfaces inside the container.
# Operators can override CMD to pass additional flags (e.g. --tls for direct
# access without a reverse proxy).
CMD ["--bind", "0.0.0.0", "--port", "9876"]

# Expected volume mounts:
#   /etc/weewx-clearskies/          config dir shared with the API and realtime containers

# ── builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

COPY pyproject.toml .
COPY README.md .
COPY weewx_clearskies_config/ weewx_clearskies_config/

# NOTE: weewx-clearskies-api is a declared dependency but is not published on
# PyPI.  To resolve it during the build you must supply an additional build
# context that points to the API source tree:
#
#   docker buildx build \
#     --build-context weewx-clearskies-api=../weewx-clearskies-api \
#     -t clearskies-config .
#
# Then add this COPY + install step before `pip install .`:
#
#   COPY --from=weewx-clearskies-api . /api-src
#   RUN pip install --no-cache-dir /api-src
#
# Alternatively, publish weewx-clearskies-api to a package index and remove
# the manual COPY step.  Until one of these is in place, the build will fail
# if pip cannot resolve weewx-clearskies-api>=0.1.0 from the default index.
RUN pip install --no-cache-dir .

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

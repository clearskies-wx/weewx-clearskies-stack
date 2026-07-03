#!/bin/bash
# install-prerequisites.sh — bare-metal (pip-installed, non-Docker) setup for
# weewx-clearskies-api and weewx-clearskies-config.
#
# Creates the system user, groups, and directories the systemd units in
# examples/systemd/ expect. Safe to re-run (idempotent).
#
# Run as root: sudo ./install-prerequisites.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root" >&2
    exit 1
fi

CREATED_USER=0
CREATED_GROUP=0
CREATED_ETC_DIR=0
CREATED_RUN_DIR=0
CREATED_WWW_DIR=0
FIXED_DB_PERMS=0

# ---------------------------------------------------------------------------
# System user
# ---------------------------------------------------------------------------
if id clearskies >/dev/null 2>&1; then
    echo "User 'clearskies' already exists — skipping."
else
    useradd --system --no-create-home --shell /usr/sbin/nologin clearskies
    CREATED_USER=1
    echo "Created system user 'clearskies'."
fi

# ---------------------------------------------------------------------------
# weewx-ro group (read-only access to the weewx SQLite DB)
# ---------------------------------------------------------------------------
if getent group weewx-ro >/dev/null 2>&1; then
    echo "Group 'weewx-ro' already exists — skipping."
else
    groupadd --system weewx-ro
    CREATED_GROUP=1
    echo "Created group 'weewx-ro'."
fi

# ---------------------------------------------------------------------------
# Group membership — clearskies needs weewx-ro (DB read) and weewx
# (socket access via the ClearSkiesLoopRelay extension).
# ---------------------------------------------------------------------------
usermod -aG weewx-ro,weewx clearskies
echo "Ensured 'clearskies' is a member of weewx-ro and weewx groups."

# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------
if [ ! -d /etc/weewx-clearskies ]; then
    mkdir -p /etc/weewx-clearskies
    CREATED_ETC_DIR=1
fi
chown clearskies:clearskies /etc/weewx-clearskies
chmod 750 /etc/weewx-clearskies

# ---------------------------------------------------------------------------
# Runtime socket directory (ClearSkiesLoopRelay writes loop.sock here)
# ---------------------------------------------------------------------------
if [ ! -d /var/run/weewx-clearskies ]; then
    mkdir -p /var/run/weewx-clearskies
    CREATED_RUN_DIR=1
fi
chown clearskies:weewx /var/run/weewx-clearskies
chmod 770 /var/run/weewx-clearskies

# ---------------------------------------------------------------------------
# Caddy web root (only if Caddy is installed on this host)
# ---------------------------------------------------------------------------
if command -v caddy >/dev/null 2>&1; then
    if [ ! -d /var/www/clearskies ]; then
        mkdir -p /var/www/clearskies
        CREATED_WWW_DIR=1
    fi
    chown caddy:caddy /var/www/clearskies
    chmod 755 /var/www/clearskies
else
    echo "Caddy not found — skipping /var/www/clearskies setup."
fi

# ---------------------------------------------------------------------------
# SQLite DB permissions (only if using SQLite; MariaDB users are unaffected)
# ---------------------------------------------------------------------------
if [ -f /var/lib/weewx/weewx.sdb ]; then
    chgrp weewx-ro /var/lib/weewx/weewx.sdb
    chmod g+r /var/lib/weewx/weewx.sdb
    FIXED_DB_PERMS=1
else
    echo "No SQLite DB at /var/lib/weewx/weewx.sdb — skipping DB permission fix."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "=== install-prerequisites.sh summary ==="
[ "$CREATED_USER" -eq 1 ] && echo "  - Created system user: clearskies" || echo "  - User clearskies: already present"
[ "$CREATED_GROUP" -eq 1 ] && echo "  - Created group: weewx-ro" || echo "  - Group weewx-ro: already present"
echo "  - clearskies group membership: weewx-ro, weewx"
[ "$CREATED_ETC_DIR" -eq 1 ] && echo "  - Created /etc/weewx-clearskies (clearskies:clearskies, 750)" || echo "  - /etc/weewx-clearskies: already present (permissions reapplied)"
[ "$CREATED_RUN_DIR" -eq 1 ] && echo "  - Created /var/run/weewx-clearskies (clearskies:weewx, 770)" || echo "  - /var/run/weewx-clearskies: already present (permissions reapplied)"
if command -v caddy >/dev/null 2>&1; then
    [ "$CREATED_WWW_DIR" -eq 1 ] && echo "  - Created /var/www/clearskies (caddy:caddy, 755)" || echo "  - /var/www/clearskies: already present (permissions reapplied)"
fi
[ "$FIXED_DB_PERMS" -eq 1 ] && echo "  - Fixed weewx.sdb permissions (group weewx-ro, g+r)"
echo
echo "Next steps: install the weewx-clearskies-api and weewx-clearskies-config"
echo "packages, populate /etc/weewx-clearskies, then enable the systemd units"
echo "in examples/systemd/."

#!/bin/bash
# setup.sh — Interactive Clear Skies deployment setup
#
# Asks the operator a few questions, detects the network environment,
# and writes the configuration files needed to start the stack.
# Works for both Docker compose and native (pip + systemd) installs.
#
# Usage:
#   ./scripts/setup.sh              # interactive
#   ./scripts/setup.sh --help       # show usage
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=lib/detect-network.sh
source "$SCRIPT_DIR/lib/detect-network.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

bold() { printf '\033[1m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
yellow() { printf '\033[33m%s\033[0m' "$1"; }

ask() {
    local prompt="$1" default="${2:-}"
    if [ -n "$default" ]; then
        printf "%s [%s]: " "$prompt" "$default"
    else
        printf "%s: " "$prompt"
    fi
    read -r REPLY
    REPLY="${REPLY:-$default}"
}

ask_choice() {
    local prompt="$1" default="$2"
    shift 2
    local i=1
    for opt in "$@"; do
        if [ "$i" -eq "$default" ]; then
            printf "  [%d] %s (recommended)\n" "$i" "$opt"
        else
            printf "  [%d] %s\n" "$i" "$opt"
        fi
        i=$((i + 1))
    done
    printf "Choice [%d]: " "$default"
    read -r REPLY
    REPLY="${REPLY:-$default}"
}

confirm() {
    local prompt="$1"
    printf "%s [Y/n]: " "$prompt"
    read -r REPLY
    case "${REPLY:-Y}" in
        [Yy]*) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Step 1: Install type
# ---------------------------------------------------------------------------

echo
echo "$(bold '━━━ Clear Skies Setup ━━━')"
echo

echo "$(bold 'Step 1: Install type')"
ask_choice "How are you deploying Clear Skies?" 1 \
    "Docker Compose (containers)" \
    "Native (pip install + systemd)"
INSTALL_TYPE="$REPLY"

# ---------------------------------------------------------------------------
# Step 2: Topology (Docker only — native is always single-host)
# ---------------------------------------------------------------------------

TOPOLOGY="single"
if [ "$INSTALL_TYPE" -eq 1 ]; then
    echo
    echo "$(bold 'Step 2: Deployment topology')"
    echo "  Clear Skies can run on one machine or split across two:"
    echo "  - Single-host: everything on this machine (simpler)"
    echo "  - Two-host: API on the weewx machine, dashboard+Caddy here (more secure)"
    ask_choice "Which topology?" 1 \
        "Single-host (all services here)" \
        "Two-host (API on weewx host, dashboard here)"
    [ "$REPLY" -eq 2 ] && TOPOLOGY="twohost"
fi

# ---------------------------------------------------------------------------
# Step 3: Network stack
# ---------------------------------------------------------------------------

echo
echo "$(bold 'Step 3: Network stack')"
detect_network

DEFAULT_CHOICE=1
case "$DETECTED_STACK" in
    dual) DEFAULT_CHOICE=3 ;;
    ipv6) DEFAULT_CHOICE=2 ;;
esac

ask_choice "Which network stack should Clear Skies use?" "$DEFAULT_CHOICE" \
    "IPv4 only" \
    "IPv6 only" \
    "Dual-stack (both)"
case "$REPLY" in
    1) NETWORK="ipv4" ;;
    2) NETWORK="ipv6" ;;
    3) NETWORK="dual" ;;
    *) NETWORK="ipv4" ;;
esac

BIND_HOST="$(bind_addr_for "$NETWORK")"

# ---------------------------------------------------------------------------
# Step 4: Domain
# ---------------------------------------------------------------------------

echo
echo "$(bold 'Step 4: Domain')"
echo "  The public hostname visitors will use to reach your weather site."
echo "  Use 'localhost' for local testing (Caddy will use a self-signed cert)."
ask "Domain" "localhost"
DOMAIN="$REPLY"

# ---------------------------------------------------------------------------
# Step 5: weewx host (two-host Docker only)
# ---------------------------------------------------------------------------

API_URL=""
if [ "$TOPOLOGY" = "twohost" ]; then
    echo
    echo "$(bold 'Step 5: weewx host')"
    echo "  The hostname or IP address of the machine running weewx and the API."
    echo "  Format: $(api_url_hint "$NETWORK")"
    ask "weewx host address" ""
    WEEWX_HOST="$REPLY"

    case "$NETWORK" in
        ipv6) API_URL="https://[${WEEWX_HOST}]:8765" ;;
        *)    API_URL="https://${WEEWX_HOST}:8765" ;;
    esac

    echo "  Testing connectivity to $API_URL ..."
    if curl -sk --connect-timeout 5 "$API_URL/health" >/dev/null 2>&1; then
        echo "  $(green '✓') API reachable"
    else
        echo "  $(yellow '!') Could not reach API at $API_URL"
        echo "    This is normal if the API is not running yet."
        echo "    Make sure the API is started before running the wizard."
        if ! confirm "  Continue anyway?"; then
            echo "Aborted."
            exit 1
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Step 6: weewx data paths
# ---------------------------------------------------------------------------

echo
echo "$(bold 'Step 6: weewx data paths')"

ask "Path to weewx.conf" "/etc/weewx/weewx.conf"
WEEWX_CONF="$REPLY"

echo "  Database type:"
ask_choice "  Which database does weewx use?" 1 \
    "SQLite" \
    "MariaDB / MySQL"
DB_TYPE="$REPLY"

WEEWX_DB_PATH="/var/lib/weewx/weewx.sdb"
DB_HOST="" DB_PORT="" DB_NAME="" DB_USER="" DB_PASS=""

if [ "$DB_TYPE" -eq 1 ]; then
    ask "Path to weewx.sdb" "/var/lib/weewx/weewx.sdb"
    WEEWX_DB_PATH="$REPLY"
else
    ask "MariaDB host" "localhost"
    DB_HOST="$REPLY"
    ask "MariaDB port" "3306"
    DB_PORT="$REPLY"
    ask "MariaDB database name" "weewx"
    DB_NAME="$REPLY"
    ask "MariaDB read-only user" "clearskies_ro"
    DB_USER="$REPLY"
    ask "MariaDB password" ""
    DB_PASS="$REPLY"
fi

# ---------------------------------------------------------------------------
# Step 7: Confirm
# ---------------------------------------------------------------------------

echo
echo "$(bold '━━━ Configuration Summary ━━━')"
echo
if [ "$INSTALL_TYPE" -eq 1 ]; then
    echo "  Install type: Docker Compose"
    echo "  Topology:     $TOPOLOGY"
else
    echo "  Install type: Native (pip + systemd)"
fi
echo "  Network:      $NETWORK (bind: $BIND_HOST)"
echo "  Domain:       $DOMAIN"
if [ "$TOPOLOGY" = "twohost" ]; then
    echo "  API URL:      $API_URL"
fi
echo "  weewx.conf:   $WEEWX_CONF"
if [ "$DB_TYPE" -eq 1 ]; then
    echo "  Database:     SQLite ($WEEWX_DB_PATH)"
else
    echo "  Database:     MariaDB ($DB_HOST:$DB_PORT/$DB_NAME)"
fi
echo

if ! confirm "Write configuration?"; then
    echo "Aborted. No files written."
    exit 0
fi

# ---------------------------------------------------------------------------
# Write configuration
# ---------------------------------------------------------------------------

echo

if [ "$INSTALL_TYPE" -eq 1 ]; then
    # ----- Docker Compose -----
    if [ "$TOPOLOGY" = "twohost" ]; then
        TARGET_DIR="$REPO_DIR/frontend-host"
    else
        TARGET_DIR="$REPO_DIR/single-host"
    fi

    mkdir -p "$TARGET_DIR/config"

    # .env
    ENV_FILE="$TARGET_DIR/.env"
    cat > "$ENV_FILE" <<ENVEOF
# Generated by setup.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
CLEARSKIES_VERSION=1.0.0b1
CLEARSKIES_DOMAIN=$DOMAIN
CLEARSKIES_BIND_HOST=$BIND_HOST
CLEARSKIES_CONFIG_DIR=./config
CLEARSKIES_SECRETS_FILE=./config/secrets.env
CLEARSKIES_HTTP_PORT=80
CLEARSKIES_HTTPS_PORT=443
ENVEOF

    if [ "$TOPOLOGY" = "twohost" ]; then
        echo "CLEARSKIES_API_URL=$API_URL" >> "$ENV_FILE"
    fi

    if [ "$TOPOLOGY" = "single" ]; then
        echo "WEEWX_CONF_PATH=$WEEWX_CONF" >> "$ENV_FILE"
        if [ "$DB_TYPE" -eq 1 ]; then
            echo "WEEWX_DB_PATH=$WEEWX_DB_PATH" >> "$ENV_FILE"
        fi
    fi

    echo "  $(green '✓') Wrote $ENV_FILE"

    # secrets.env
    SECRETS_FILE="$TARGET_DIR/config/secrets.env"
    cat > "$SECRETS_FILE" <<SECEOF
# Generated by setup.sh — mode 0600
# Database credentials (MariaDB only)
WEEWX_CLEARSKIES_DB_USER=${DB_USER}
WEEWX_CLEARSKIES_DB_PASSWORD=${DB_PASS}

# Provider API keys (set after running the wizard)
# WEEWX_CLEARSKIES_AERIS_CLIENT_ID=
# WEEWX_CLEARSKIES_AERIS_CLIENT_SECRET=
# WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID=
# WEEWX_CLEARSKIES_IQAIR_KEY=
SECEOF
    chmod 600 "$SECRETS_FILE"
    echo "  $(green '✓') Wrote $SECRETS_FILE (mode 600)"

    # Write a minimal api.conf with the bind address so the API starts
    # on the correct network stack. The wizard will fill in the rest.
    API_CONF="$TARGET_DIR/config/api.conf"
    if [ ! -f "$API_CONF" ]; then
        cat > "$API_CONF" <<APIEOF
# Generated by setup.sh — minimal config for first start.
# The setup wizard will populate the remaining settings.
[api]
bind_host = $BIND_HOST
bind_port = 8765

[health]
bind_host = 127.0.0.1
bind_port = 8081
APIEOF
        echo "  $(green '✓') Wrote $API_CONF (bind: $BIND_HOST)"
    else
        echo "  $(yellow '!') $API_CONF already exists — not overwritten"
    fi

    echo
    echo "$(bold 'Next steps:')"
    echo "  cd $TARGET_DIR"
    echo "  docker compose up -d"
    echo "  # Then open https://$DOMAIN/wizard in your browser"

else
    # ----- Native (pip + systemd) -----
    NETWORK_ENV="/etc/weewx-clearskies/network.env"

    if [ "$(id -u)" -ne 0 ]; then
        echo "  Native install writes to /etc/weewx-clearskies/ — run with sudo."
        echo "  Example: sudo $0"
        exit 1
    fi

    # Run prerequisites if not already done
    if ! id clearskies >/dev/null 2>&1; then
        echo "  Running install-prerequisites.sh first..."
        bash "$SCRIPT_DIR/install-prerequisites.sh"
        echo
    fi

    # Write network.env
    cat > "$NETWORK_ENV" <<NETEOF
# Generated by setup.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Network stack: $NETWORK
CLEARSKIES_BIND_HOST=$BIND_HOST
NETEOF
    chown clearskies:clearskies "$NETWORK_ENV"
    chmod 640 "$NETWORK_ENV"
    echo "  $(green '✓') Wrote $NETWORK_ENV"

    # Write secrets.env if it doesn't exist
    SECRETS_FILE="/etc/weewx-clearskies/secrets.env"
    if [ ! -f "$SECRETS_FILE" ]; then
        cat > "$SECRETS_FILE" <<SECEOF
# Generated by setup.sh — mode 0600
WEEWX_CLEARSKIES_DB_USER=${DB_USER}
WEEWX_CLEARSKIES_DB_PASSWORD=${DB_PASS}
SECEOF
        chown clearskies:clearskies "$SECRETS_FILE"
        chmod 600 "$SECRETS_FILE"
        echo "  $(green '✓') Wrote $SECRETS_FILE (mode 600)"
    else
        echo "  $(yellow '!') $SECRETS_FILE already exists — not overwritten"
    fi

    echo
    echo "$(bold 'Next steps:')"
    echo "  pip install --pre weewx-clearskies-api weewx-clearskies-config"
    echo "  sudo cp examples/systemd/weewx-clearskies-*.service /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now weewx-clearskies-api weewx-clearskies-config"
    echo "  # Then open https://$DOMAIN/wizard in your browser"
fi

echo
echo "$(green 'Setup complete.')"

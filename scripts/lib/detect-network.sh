#!/bin/bash
# detect-network.sh — shared network detection functions
# Sourced by setup scripts; not run directly.

# Returns 0 if the host has at least one non-loopback IPv4 address.
has_ipv4() {
    ip -4 addr show scope global 2>/dev/null | grep -q 'inet ' 2>/dev/null
}

# Returns 0 if the host has at least one non-loopback IPv6 address (GUA or ULA, not link-local).
has_ipv6() {
    ip -6 addr show scope global 2>/dev/null | grep -q 'inet6 ' 2>/dev/null
}

# Returns the first non-loopback IPv4 address.
get_ipv4_addr() {
    ip -4 addr show scope global 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -1
}

# Returns the first non-loopback IPv6 GUA/ULA address.
get_ipv6_addr() {
    ip -6 addr show scope global 2>/dev/null | grep -oP 'inet6 \K[0-9a-f:]+' | head -1
}

# Tests whether a remote host is reachable on a given port via IPv4.
# Usage: test_ipv4_reach <host> <port>
test_ipv4_reach() {
    local host="$1" port="$2"
    timeout 3 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null
}

# Tests whether a remote host is reachable on a given port via IPv6.
# Usage: test_ipv6_reach <host> <port>
test_ipv6_reach() {
    local host="$1" port="$2"
    timeout 3 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null
}

# Prints a network detection summary and sets DETECTED_STACK to ipv4, ipv6, or dual.
detect_network() {
    local v4=0 v6=0

    echo "  Detecting network configuration..."
    if has_ipv4; then
        v4=1
        echo "    IPv4: available ($(get_ipv4_addr))"
    else
        echo "    IPv4: not available"
    fi

    if has_ipv6; then
        v6=1
        echo "    IPv6: available ($(get_ipv6_addr))"
    else
        echo "    IPv6: not available"
    fi

    if [ "$v4" -eq 1 ] && [ "$v6" -eq 1 ]; then
        DETECTED_STACK="dual"
        echo "    Recommendation: Dual-stack (both available)"
    elif [ "$v4" -eq 1 ]; then
        DETECTED_STACK="ipv4"
        echo "    Recommendation: IPv4 only"
    elif [ "$v6" -eq 1 ]; then
        DETECTED_STACK="ipv6"
        echo "    Recommendation: IPv6 only"
    else
        DETECTED_STACK="ipv4"
        echo "    WARNING: No global addresses found. Defaulting to IPv4."
    fi
}

# Maps a stack choice to a bind address.
# Usage: bind_addr_for <ipv4|ipv6|dual>
bind_addr_for() {
    case "$1" in
        ipv4) echo "0.0.0.0" ;;
        ipv6) echo "::" ;;
        dual) echo "*" ;;
        *)    echo "0.0.0.0" ;;
    esac
}

# Maps a stack choice to an example API URL format hint.
api_url_hint() {
    case "$1" in
        ipv4) echo "http://<ipv4-address>:8765  (e.g., http://192.168.1.20:8765)" ;;
        ipv6) echo "http://[<ipv6-address>]:8765  (e.g., http://[fd00::20]:8765)" ;;
        dual) echo "http://<hostname>:8765  (e.g., http://weewx.local:8765)" ;;
        *)    echo "http://<address>:8765" ;;
    esac
}

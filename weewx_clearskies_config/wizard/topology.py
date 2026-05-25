"""Deployment topology helpers and shared-secret generation.

Two supported topologies:
  same-host  — API, realtime, and dashboard all on one host.  Services
               bind loopback; no shared secret needed.
  cross-host — Dashboard on a separate host.  Services bind 0.0.0.0
               (all IPv4 interfaces); a shared secret is required to
               authenticate the dashboard proxy to the API.

Note: do NOT use :: for cross-host binds.  Uvicorn sets IPV6_V6ONLY=1 on
IPv6 sockets, making :: IPv6-only regardless of the kernel bindv6only setting.
"""

from __future__ import annotations

import secrets
from typing import Any


def generate_proxy_secret() -> str:
    """Generate a 64-character hex shared secret for cross-host deployments."""
    return secrets.token_hex(32)


def topology_defaults(same_host: bool) -> dict[str, Any]:
    """Return default bind addresses and flags for the given topology.

    Args:
        same_host: True → services bind ``127.0.0.1`` (loopback only).
                   False → services bind ``0.0.0.0`` (all IPv4 interfaces).

    Returns a dict with keys:
        api_bind_host, api_bind_port,
        realtime_bind_host, realtime_bind_port,
        needs_proxy_secret.
    """
    bind_host = "127.0.0.1" if same_host else "0.0.0.0"
    return {
        "api_bind_host": bind_host,
        "api_bind_port": 8765,
        "realtime_bind_host": bind_host,
        "realtime_bind_port": 8766,
        "needs_proxy_secret": not same_host,
    }

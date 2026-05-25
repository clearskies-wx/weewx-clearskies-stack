"""Tests for weewx_clearskies_config.wizard.topology — deployment topology helpers."""

from __future__ import annotations

import pytest

from weewx_clearskies_config.wizard.topology import generate_proxy_secret, topology_defaults


# ---------------------------------------------------------------------------
# topology_defaults
# ---------------------------------------------------------------------------


def test_topology_defaults_same_host_binds_loopback():
    defaults = topology_defaults(same_host=True)
    assert defaults["api_bind_host"] == "127.0.0.1"
    assert defaults["realtime_bind_host"] == "127.0.0.1"


def test_topology_defaults_cross_host_binds_all_ipv4_interfaces():
    # :: is NOT used: uvicorn sets IPV6_V6ONLY=1 on IPv6 sockets, so :: is
    # IPv6-only in practice.  0.0.0.0 gives reliable all-interfaces behaviour.
    defaults = topology_defaults(same_host=False)
    assert defaults["api_bind_host"] == "0.0.0.0"
    assert defaults["realtime_bind_host"] == "0.0.0.0"


def test_topology_defaults_same_host_does_not_need_proxy_secret():
    defaults = topology_defaults(same_host=True)
    assert defaults["needs_proxy_secret"] is False


def test_topology_defaults_cross_host_requires_proxy_secret():
    defaults = topology_defaults(same_host=False)
    assert defaults["needs_proxy_secret"] is True


def test_topology_defaults_api_port_is_8765():
    defaults = topology_defaults(same_host=True)
    assert defaults["api_bind_port"] == 8765


def test_topology_defaults_realtime_port_is_8766():
    defaults = topology_defaults(same_host=True)
    assert defaults["realtime_bind_port"] == 8766


def test_topology_defaults_returns_all_expected_keys():
    expected_keys = {
        "api_bind_host",
        "api_bind_port",
        "realtime_bind_host",
        "realtime_bind_port",
        "needs_proxy_secret",
    }
    defaults = topology_defaults(same_host=True)
    assert set(defaults.keys()) == expected_keys


# ---------------------------------------------------------------------------
# generate_proxy_secret
# ---------------------------------------------------------------------------


def test_generate_proxy_secret_returns_64_char_hex():
    secret = generate_proxy_secret()
    assert len(secret) == 64
    assert all(c in "0123456789abcdef" for c in secret)


def test_generate_proxy_secret_produces_unique_values_on_each_call():
    """Two consecutive calls must not produce the same secret."""
    s1 = generate_proxy_secret()
    s2 = generate_proxy_secret()
    assert s1 != s2

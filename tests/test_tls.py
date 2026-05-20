"""Tests for weewx_clearskies_config.tls — self-signed cert generation."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
from cryptography import x509


from weewx_clearskies_config.tls import (
    generate_self_signed_cert,
    get_cert_fingerprint,
    load_or_generate_cert,
)


def _load_cert(cert_path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(cert_path.read_bytes())


def _san_entries(cert: x509.Certificate) -> set[str]:
    """Return all SAN entries as strings for easy assertion."""
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return set()
    names: set[str] = set()
    for entry in ext.value:
        if isinstance(entry, x509.DNSName):
            names.add(entry.value)
        elif isinstance(entry, x509.IPAddress):
            names.add(str(entry.value))
    return names


# ---------------------------------------------------------------------------
# generate_self_signed_cert
# ---------------------------------------------------------------------------


def test_generate_self_signed_cert_creates_cert_and_key_files(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["127.0.0.1"], cert_path, key_path)
    assert cert_path.exists()
    assert key_path.exists()


def test_generate_self_signed_cert_always_includes_localhost_san(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["192.168.1.10"], cert_path, key_path)
    sans = _san_entries(_load_cert(cert_path))
    assert "localhost" in sans
    assert "127.0.0.1" in sans
    assert "::1" in sans


def test_generate_self_signed_cert_includes_provided_ipv4_address(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["192.168.7.20"], cert_path, key_path)
    sans = _san_entries(_load_cert(cert_path))
    assert "192.168.7.20" in sans


def test_generate_self_signed_cert_includes_provided_hostname(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["weather.local"], cert_path, key_path)
    sans = _san_entries(_load_cert(cert_path))
    assert "weather.local" in sans


def test_generate_self_signed_cert_handles_ipv6_bracketed_literal(tmp_path: Path):
    """Brackets are stripped before the SAN is built from an IPv6 literal."""
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["[::1]"], cert_path, key_path)
    sans = _san_entries(_load_cert(cert_path))
    assert "::1" in sans


def test_generate_self_signed_cert_key_file_is_readable(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["127.0.0.1"], cert_path, key_path)
    # Key must start with PEM header
    assert key_path.read_text().startswith("-----BEGIN")


def test_generate_self_signed_cert_deduplicates_loopback_entries(tmp_path: Path):
    """If the caller explicitly provides 127.0.0.1, it should not appear twice in SANs."""
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    # Explicitly list 127.0.0.1 which is also the always-included loopback.
    generate_self_signed_cert(["127.0.0.1", "::1"], cert_path, key_path)
    cert = _load_cert(cert_path)
    ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    ip_entries = [
        e for e in ext.value
        if isinstance(e, x509.IPAddress) and e.value == ipaddress.ip_address("127.0.0.1")
    ]
    assert len(ip_entries) == 1, "127.0.0.1 must appear exactly once in SANs"


# ---------------------------------------------------------------------------
# get_cert_fingerprint
# ---------------------------------------------------------------------------


def test_get_cert_fingerprint_returns_colon_separated_hex(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["127.0.0.1"], cert_path, key_path)
    fp = get_cert_fingerprint(cert_path)
    # SHA-256 fingerprint: 64 hex chars = 32 pairs, 31 colons → 32*2 + 31 = 95 chars
    assert ":" in fp
    parts = fp.split(":")
    assert len(parts) == 32
    for part in parts:
        assert len(part) == 2
        assert all(c in "0123456789ABCDEF" for c in part)


def test_get_cert_fingerprint_is_stable_across_reads(tmp_path: Path):
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    generate_self_signed_cert(["127.0.0.1"], cert_path, key_path)
    fp1 = get_cert_fingerprint(cert_path)
    fp2 = get_cert_fingerprint(cert_path)
    assert fp1 == fp2


# ---------------------------------------------------------------------------
# load_or_generate_cert
# ---------------------------------------------------------------------------


def test_load_or_generate_cert_creates_cert_on_first_call(tmp_path: Path):
    cert_path, key_path = load_or_generate_cert(["127.0.0.1"], tmp_path)
    assert cert_path.exists()
    assert key_path.exists()


def test_load_or_generate_cert_reuses_existing_cert_on_second_call(tmp_path: Path):
    """If the existing cert already covers the requested SANs, it must not be regenerated."""
    _cert1, _key1 = load_or_generate_cert(["127.0.0.1"], tmp_path)
    cert_path_before = (tmp_path / "tls.crt").read_bytes()

    _cert2, _key2 = load_or_generate_cert(["127.0.0.1"], tmp_path)
    cert_path_after = (tmp_path / "tls.crt").read_bytes()

    assert cert_path_before == cert_path_after, "Cert must not be regenerated when SANs match"


def test_load_or_generate_cert_regenerates_when_san_missing(tmp_path: Path):
    """A new SAN requirement not covered by the existing cert must trigger regeneration."""
    load_or_generate_cert(["127.0.0.1"], tmp_path)
    cert_first = (tmp_path / "tls.crt").read_bytes()

    # Request a SAN that was not in the first cert.
    load_or_generate_cert(["127.0.0.1", "192.168.1.50"], tmp_path)
    cert_second = (tmp_path / "tls.crt").read_bytes()

    assert cert_first != cert_second, "Cert must be regenerated when a new SAN is required"

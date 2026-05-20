"""Tests for weewx_clearskies_config.auth — security-critical module.

Covers password hashing, bootstrap tokens, session management, rate limiting,
and secrets file I/O.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from weewx_clearskies_config.auth import (
    BootstrapManager,
    RateLimiter,
    SessionManager,
    hash_password,
    read_secrets,
    verify_password,
    write_secrets,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_hash_password_and_verify_password_round_trip_succeeds():
    password = "CorrectHorseBatteryStaple!"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_with_wrong_password_returns_false():
    hashed = hash_password("right-password-long-enough")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_produces_different_hashes_for_same_input():
    """Argon2 embeds a per-hash salt — same password must never produce the same hash."""
    pw = "same-password-every-time!"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2


def test_verify_password_with_empty_password_returns_false():
    hashed = hash_password("nonempty-password-here")
    assert verify_password("", hashed) is False


# ---------------------------------------------------------------------------
# BootstrapManager
# ---------------------------------------------------------------------------


def test_bootstrap_manager_generate_returns_64_char_hex():
    bm = BootstrapManager()
    token = bm.generate()
    assert len(token) == 64
    assert all(c in "0123456789abcdef" for c in token)


def test_bootstrap_manager_validate_correct_token_returns_true():
    bm = BootstrapManager()
    token = bm.generate()
    assert bm.validate(token) is True


def test_bootstrap_manager_validate_correct_token_invalidates_on_use():
    """After validate() consumes the token, a second call must return False."""
    bm = BootstrapManager()
    token = bm.generate()
    bm.validate(token)
    assert bm.validate(token) is False


def test_bootstrap_manager_validate_wrong_token_returns_false():
    bm = BootstrapManager()
    bm.generate()
    assert bm.validate("0" * 64) is False


def test_bootstrap_manager_validate_before_generate_returns_false():
    bm = BootstrapManager()
    assert bm.validate("anything") is False


def test_bootstrap_manager_generate_twice_invalidates_first_token():
    """Calling generate() a second time replaces the first token."""
    bm = BootstrapManager()
    first = bm.generate()
    _second = bm.generate()
    # First token is no longer valid once a new one was generated.
    assert bm.validate(first) is False


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


def test_session_manager_create_and_get_username_round_trip():
    sm = SessionManager()
    session_id = sm.create("alice")
    assert sm.get_username(session_id) == "alice"


def test_session_manager_get_username_unknown_session_returns_none():
    sm = SessionManager()
    assert sm.get_username("nonexistent-session-id") is None


def test_session_manager_delete_removes_session():
    sm = SessionManager()
    session_id = sm.create("bob")
    sm.delete(session_id)
    assert sm.get_username(session_id) is None


def test_session_manager_delete_nonexistent_session_does_not_raise():
    sm = SessionManager()
    # Must not raise
    sm.delete("does-not-exist")


def test_session_manager_create_returns_unique_ids_per_user():
    sm = SessionManager()
    id1 = sm.create("alice")
    id2 = sm.create("alice")
    assert id1 != id2


def test_session_manager_cookie_kwargs_include_httponly_and_samesite():
    sm = SessionManager(tls_enabled=False)
    kwargs = sm.cookie_kwargs
    assert kwargs["httponly"] is True
    assert kwargs["samesite"] == "strict"


def test_session_manager_tls_enabled_sets_secure_flag():
    sm = SessionManager(tls_enabled=True)
    assert sm.cookie_kwargs["secure"] is True


def test_session_manager_tls_disabled_clears_secure_flag():
    sm = SessionManager(tls_enabled=False)
    assert sm.cookie_kwargs["secure"] is False


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_first_five_failures():
    rl = RateLimiter()
    ip = "192.168.1.100"
    # 4 failures — should NOT be throttled yet
    for _ in range(4):
        rl.record_failure(ip)
    assert rl.is_throttled(ip) is False


def test_rate_limiter_throttles_on_fifth_failure():
    rl = RateLimiter()
    ip = "10.0.0.1"
    for _ in range(5):
        rl.record_failure(ip)
    assert rl.is_throttled(ip) is True


def test_rate_limiter_record_success_clears_throttle():
    rl = RateLimiter()
    ip = "10.0.0.2"
    for _ in range(5):
        rl.record_failure(ip)
    assert rl.is_throttled(ip) is True
    rl.record_success(ip)
    assert rl.is_throttled(ip) is False


def test_rate_limiter_different_ips_are_independent():
    rl = RateLimiter()
    ip_a = "10.0.0.10"
    ip_b = "10.0.0.11"
    for _ in range(5):
        rl.record_failure(ip_a)
    assert rl.is_throttled(ip_a) is True
    assert rl.is_throttled(ip_b) is False


def test_rate_limiter_not_throttled_initially():
    rl = RateLimiter()
    assert rl.is_throttled("192.168.99.1") is False


# ---------------------------------------------------------------------------
# Secrets file I/O
# ---------------------------------------------------------------------------


def test_write_secrets_and_read_secrets_round_trip(config_dir: Path):
    data = {
        "WEEWX_CLEARSKIES_ADMIN_USERNAME": "operator",
        "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": "somehashvalue",
        "WEEWX_CLEARSKIES_DB_PASSWORD": "s3cr3t!",
    }
    write_secrets(data)
    result = read_secrets()
    assert result == data


def test_read_secrets_returns_empty_dict_when_file_absent(config_dir: Path):
    result = read_secrets()
    assert result == {}


def test_write_secrets_creates_parent_directory(tmp_path: Path):
    import os

    nested = tmp_path / "deep" / "nested"
    os.environ["WEEWX_CLEARSKIES_CONFIG_DIR"] = str(nested)
    try:
        write_secrets({"KEY": "VALUE"})
        assert (nested / "secrets.env").exists()
    finally:
        os.environ.pop("WEEWX_CLEARSKIES_CONFIG_DIR", None)


def test_write_secrets_ignores_comment_lines_on_read(config_dir: Path):
    """Parser must skip comment and blank lines in secrets.env."""
    secrets_path = config_dir / "secrets.env"
    secrets_path.write_text(
        "# This is a comment\n\nKEY_A=value_a\n\n# Another comment\nKEY_B=value_b\n",
        encoding="utf-8",
    )
    result = read_secrets()
    assert result == {"KEY_A": "value_a", "KEY_B": "value_b"}


def test_write_secrets_handles_values_with_equals_sign(config_dir: Path):
    """A value that contains '=' must be preserved correctly (partition on first '=')."""
    write_secrets({"TOKEN": "abc=def=ghi"})
    result = read_secrets()
    assert result["TOKEN"] == "abc=def=ghi"

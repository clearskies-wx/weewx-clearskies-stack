"""Tests for weewx_clearskies_config.cli — CLI flag parsing via click.testing.CliRunner.

Server startup (uvicorn.run) is always mocked out so tests never bind a port.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from weewx_clearskies_config.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# --show-secrets
# ---------------------------------------------------------------------------


def test_show_secrets_with_no_secrets_prints_no_secrets_found(config_dir: Path):
    result = _runner().invoke(cli, ["--show-secrets"])
    assert result.exit_code == 0
    assert "No secrets found." in result.output


def test_show_secrets_with_populated_secrets_prints_key_value_pairs(config_dir: Path):
    from weewx_clearskies_config.auth import write_secrets
    write_secrets({"MY_KEY": "my_value", "OTHER_KEY": "other_value"})
    result = _runner().invoke(cli, ["--show-secrets"])
    assert result.exit_code == 0
    assert "MY_KEY=my_value" in result.output
    assert "OTHER_KEY=other_value" in result.output


# ---------------------------------------------------------------------------
# --reset-admin-password
# ---------------------------------------------------------------------------


def test_reset_admin_password_clears_admin_credentials(config_dir: Path):
    from weewx_clearskies_config.auth import read_secrets, write_secrets
    write_secrets({
        "WEEWX_CLEARSKIES_ADMIN_USERNAME": "admin",
        "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": "somehash",
        "OTHER_KEY": "preserved",
    })
    result = _runner().invoke(cli, ["--reset-admin-password"])
    assert result.exit_code == 0
    secrets = read_secrets()
    assert "WEEWX_CLEARSKIES_ADMIN_USERNAME" not in secrets
    assert "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH" not in secrets
    # Unrelated keys must survive
    assert secrets.get("OTHER_KEY") == "preserved"


def test_reset_admin_password_prints_confirmation_message(config_dir: Path):
    result = _runner().invoke(cli, ["--reset-admin-password"])
    assert result.exit_code == 0
    assert "Admin credentials cleared" in result.output


# ---------------------------------------------------------------------------
# --localhost and --bind mutual exclusion
# ---------------------------------------------------------------------------


def test_localhost_and_bind_together_exits_with_error():
    result = _runner().invoke(cli, ["--localhost", "--bind", "192.168.1.1"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------


def test_help_flag_prints_usage_and_exits_zero():
    result = _runner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "usage" in result.output.lower() or "Usage" in result.output


def test_help_flag_mentions_bind_and_port_options():
    result = _runner().invoke(cli, ["--help"])
    assert "--bind" in result.output
    assert "--port" in result.output


def test_help_flag_mentions_tls_and_show_secrets_options():
    result = _runner().invoke(cli, ["--help"])
    assert "--tls" in result.output
    assert "--show-secrets" in result.output


# ---------------------------------------------------------------------------
# Server startup path (mocked uvicorn)
# ---------------------------------------------------------------------------


def test_default_invocation_calls_uvicorn_run(config_dir: Path):
    """When no action-only flags are given, the server should start via uvicorn.run."""
    with patch("uvicorn.run") as mock_uvicorn:
        result = _runner().invoke(cli, [])
    mock_uvicorn.assert_called_once()
    # Exit code is None/0 when uvicorn.run returns normally (mock does nothing)
    assert result.exit_code in (0, None)


def test_localhost_flag_passes_127_0_0_1_to_uvicorn(config_dir: Path):
    with patch("uvicorn.run") as mock_uvicorn:
        _runner().invoke(cli, ["--localhost"])
    call_kwargs = mock_uvicorn.call_args
    assert call_kwargs is not None
    # host can be positional or keyword
    host_arg = call_kwargs.kwargs.get("host") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    )
    assert host_arg == "127.0.0.1"


def test_port_flag_is_passed_to_uvicorn(config_dir: Path):
    with patch("uvicorn.run") as mock_uvicorn:
        _runner().invoke(cli, ["--port", "12345"])
    call_kwargs = mock_uvicorn.call_args
    assert call_kwargs is not None
    port_arg = call_kwargs.kwargs.get("port")
    assert port_arg == 12345


def test_reset_config_flag_exits_without_starting_server(config_dir: Path):
    with patch("uvicorn.run") as mock_uvicorn:
        result = _runner().invoke(cli, ["--reset"])
    mock_uvicorn.assert_not_called()
    assert result.exit_code == 0

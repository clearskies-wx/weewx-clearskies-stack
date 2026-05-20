"""Shared fixtures for weewx-clearskies-config test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Temp config directory; sets WEEWX_CLEARSKIES_CONFIG_DIR for auth helpers."""
    os.environ["WEEWX_CLEARSKIES_CONFIG_DIR"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("WEEWX_CLEARSKIES_CONFIG_DIR", None)


@pytest.fixture()
def test_app(config_dir: Path):
    """FastAPI application with bootstrap manager; TLS disabled for test speed."""
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager

    config = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=BootstrapManager(),
    )
    return create_app(config)


@pytest.fixture()
def client(test_app):
    """Starlette TestClient wrapping the FastAPI test app."""
    from starlette.testclient import TestClient

    return TestClient(test_app, raise_server_exceptions=True)


@pytest.fixture()
def authed_client(test_app, config_dir: Path):
    """TestClient with a pre-populated admin credential and an active session cookie.

    Writes admin username + Argon2 hash directly to secrets.env so the login
    route can authenticate without exercising the bootstrap flow.
    """
    from weewx_clearskies_config.auth import hash_password, write_secrets
    from starlette.testclient import TestClient

    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "testadmin",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("CorrectHorseBatteryStaple!"),
        }
    )

    with TestClient(test_app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/login",
            data={"username": "testadmin", "password": "CorrectHorseBatteryStaple!"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303), f"Login pre-condition failed: {resp.status_code}"
        yield c


@pytest.fixture()
def sample_weewx_conf(tmp_path: Path) -> str:
    """Minimal weewx.conf fixture with realistic MariaDB connection parameters."""
    conf = tmp_path / "weewx.conf"
    conf.write_text(
        """
[DatabaseTypes]
    [[archive_mysql]]
        host = 192.168.7.20
        user = weewx
        password = testpass123
        port = 3306

[Databases]
    [[archive_mysql]]
        database_name = weewx

[Station]
    station_type = Simulator
    location = "Fairfax, Virginia"
    latitude = 38.8894
    longitude = -77.0352
    altitude = 50, foot
""",
        encoding="utf-8",
    )
    return str(conf)

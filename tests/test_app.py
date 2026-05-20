"""Tests for weewx_clearskies_config.app — FastAPI route behaviour.

Uses the shared `client` fixture (Starlette TestClient, TLS disabled).
All file I/O is isolated in the `config_dir` (tmp_path) fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weewx_clearskies_config.auth import hash_password, write_secrets


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_200_with_status_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# / (root redirect logic)
# ---------------------------------------------------------------------------


def test_root_redirects_to_bootstrap_when_no_admin_credentials(client, config_dir: Path):
    # config_dir is empty — no secrets.env yet
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].endswith("/bootstrap")


def test_root_redirects_to_login_when_admin_credentials_exist_and_api_conf_present(
    client, config_dir: Path
):
    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "admin",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("test-password-ok"),
        }
    )
    # Create a minimal api.conf so the root handler picks /login
    (config_dir / "api.conf").write_text("[server]\nbind_host = 127.0.0.1\n")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].endswith("/login")


def test_root_redirects_to_wizard_when_api_conf_absent(client, config_dir: Path):
    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "admin",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("test-password-ok"),
        }
    )
    # No api.conf → wizard redirect
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].endswith("/wizard")


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------


def test_get_login_returns_200_html(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /login — authentication
# ---------------------------------------------------------------------------


def test_post_login_with_correct_credentials_sets_session_cookie_and_redirects(
    client, config_dir: Path
):
    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "operator",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("ValidPassword123!"),
        }
    )
    resp = client.post(
        "/login",
        data={"username": "operator", "password": "ValidPassword123!"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "clearskies_session" in resp.cookies


def test_post_login_with_wrong_password_returns_401(client, config_dir: Path):
    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "operator",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("CorrectPassword1!"),
        }
    )
    resp = client.post(
        "/login",
        data={"username": "operator", "password": "WrongPassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_post_login_with_wrong_username_returns_401(client, config_dir: Path):
    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "rightuser",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("CorrectPassword1!"),
        }
    )
    resp = client.post(
        "/login",
        data={"username": "wronguser", "password": "CorrectPassword1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


def test_post_logout_redirects_to_login(authed_client):
    resp = authed_client.post("/logout", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].endswith("/login")


def test_post_logout_clears_session_cookie(authed_client):
    resp = authed_client.post("/logout", follow_redirects=False)
    # Cookie should be deleted (empty value or set-cookie header with max-age=0)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "clearskies_session" in set_cookie


# ---------------------------------------------------------------------------
# GET /bootstrap
# ---------------------------------------------------------------------------


def test_get_bootstrap_returns_200_html(client):
    resp = client.get("/bootstrap")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /bootstrap — credential setup flow
# ---------------------------------------------------------------------------


def test_post_bootstrap_with_valid_token_sets_credentials_and_redirects(
    test_app, config_dir: Path
):
    """Generate a bootstrap token from the app's BootstrapManager, then use it."""
    from starlette.testclient import TestClient
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager, read_secrets

    bm = BootstrapManager()
    token = bm.generate()
    cfg = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=bm,
    )
    app = create_app(cfg)

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/bootstrap",
            params={"token": token},
            data={
                "username": "newadmin",
                "password": "SecurePassword1234!",
                "confirm_password": "SecurePassword1234!",
            },
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303)
    secrets = read_secrets()
    assert secrets.get("WEEWX_CLEARSKIES_ADMIN_USERNAME") == "newadmin"
    assert "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH" in secrets


def test_post_bootstrap_with_invalid_token_returns_400(test_app, config_dir: Path):
    from starlette.testclient import TestClient
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager

    bm = BootstrapManager()
    bm.generate()  # generate but don't use the real token
    cfg = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=bm,
    )
    app = create_app(cfg)

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/bootstrap",
            params={"token": "0" * 64},
            data={
                "username": "attacker",
                "password": "AnyPassword123!",
                "confirm_password": "AnyPassword123!",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400


def test_post_bootstrap_with_mismatched_passwords_returns_400(test_app, config_dir: Path):
    from starlette.testclient import TestClient
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager

    bm = BootstrapManager()
    token = bm.generate()
    cfg = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=bm,
    )
    app = create_app(cfg)

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/bootstrap",
            params={"token": token},
            data={
                "username": "admin",
                "password": "PasswordAAA123!",
                "confirm_password": "PasswordBBB456!",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400


def test_post_bootstrap_with_password_too_short_returns_400(test_app, config_dir: Path):
    from starlette.testclient import TestClient
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager

    bm = BootstrapManager()
    token = bm.generate()
    cfg = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=bm,
    )
    app = create_app(cfg)

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/bootstrap",
            params={"token": token},
            data={
                "username": "admin",
                "password": "short",
                "confirm_password": "short",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting (6th failed login → 429)
# ---------------------------------------------------------------------------


def test_rate_limiting_sixth_failed_login_returns_429(config_dir: Path):
    """After 5 failed logins the rate limiter throttles; 6th POST must return 429."""
    from starlette.testclient import TestClient
    from weewx_clearskies_config.app import AppConfig, create_app
    from weewx_clearskies_config.auth import BootstrapManager

    bm = BootstrapManager()
    cfg = AppConfig(
        bind_host="127.0.0.1",
        bind_port=9876,
        tls_enabled=False,
        tls_cert_path=None,
        tls_key_path=None,
        config_dir=config_dir,
        bootstrap_manager=bm,
    )
    app = create_app(cfg)

    write_secrets(
        {
            "WEEWX_CLEARSKIES_ADMIN_USERNAME": "admin",
            "WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH": hash_password("RealPassword123!"),
        }
    )

    with TestClient(app, raise_server_exceptions=True) as c:
        for _ in range(5):
            c.post(
                "/login",
                data={"username": "admin", "password": "BadPassword"},
                follow_redirects=False,
            )
        resp = c.post(
            "/login",
            data={"username": "admin", "password": "BadPassword"},
            follow_redirects=False,
        )

    assert resp.status_code == 429

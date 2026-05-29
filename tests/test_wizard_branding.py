"""Tests for the appearance step (step 8) of the setup wizard.

Covers:
  - GET /wizard/step/8 — page loads with existing URL values pre-filled
  - POST /wizard/step/8 — URL-only (no file) path saves correctly
  - POST /wizard/step/8 — file upload (logo light) is saved and URL stored
  - POST /wizard/step/8 — file upload (logo dark) is saved and URL stored
  - POST /wizard/step/8 — file upload (favicon) is saved and URL stored
  - POST /wizard/step/8 — file upload with wrong extension returns 422
  - POST /wizard/step/8 — file upload exceeding size limit returns 422
  - POST /wizard/step/8 — uploaded file takes precedence over URL text input
  - Filename sanitisation — _sanitise_filename strips unsafe characters
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def authed_client(test_app, config_dir: Path):
    """TestClient with an active admin session."""
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
        assert resp.status_code in (302, 303), f"Login failed: {resp.status_code}"
        yield c


def _get_state(client):
    """Return the WizardState for the client's current session."""
    from weewx_clearskies_config.wizard.state import get_wizard_state

    session_cookie = client.cookies.get("clearskies_session")
    return get_wizard_state(session_cookie) if session_cookie else None


# Minimal valid 1×1 PNG (67 bytes) — safe to use as a test fixture.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"  # signature
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal valid SVG.
_TINY_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'

# Minimal valid ICO (22-byte header; enough for extension-based validation).
_TINY_ICO = b"\x00\x00\x01\x00\x01\x00\x01\x01\x00\x00\x01\x00\x18\x00\x00\x00\x00\x00"


# ---------------------------------------------------------------------------
# 1. GET /wizard/step/8 — page loads
# ---------------------------------------------------------------------------


def test_branding_get_returns_200_html(authed_client):
    resp = authed_client.get("/wizard/step/8")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_branding_get_contains_site_title_input(authed_client):
    resp = authed_client.get("/wizard/step/8")
    assert "site_title" in resp.text


def test_branding_get_contains_file_inputs(authed_client):
    resp = authed_client.get("/wizard/step/8")
    assert "logo_light_file" in resp.text
    assert "logo_dark_file" in resp.text
    assert "favicon_file" in resp.text


def test_branding_get_prefills_existing_url(authed_client):
    """If state already has a URL, the form pre-fills it."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    cookie = authed_client.cookies.get("clearskies_session")
    state = get_wizard_state(cookie)
    state.logo_light_url = "https://example.com/logo.png"
    save_wizard_state(cookie, state)

    resp = authed_client.get("/wizard/step/8")
    assert "https://example.com/logo.png" in resp.text


# ---------------------------------------------------------------------------
# 2. POST /wizard/step/8 — URL-only path (no file uploads)
# ---------------------------------------------------------------------------


def test_branding_post_url_only_saves_state(authed_client):
    resp = authed_client.post(
        "/wizard/step/8",
        data={
            "site_title": "My Station",
            "logo_light_url": "https://example.com/light.png",
            "logo_dark_url": "https://example.com/dark.png",
            "favicon_url": "https://example.com/fav.ico",
        },
    )
    # Successful post advances to step 9 (review), returning 200 HTML fragment.
    assert resp.status_code == 200
    state = _get_state(authed_client)
    assert state.site_title == "My Station"
    assert state.logo_light_url == "https://example.com/light.png"
    assert state.logo_dark_url == "https://example.com/dark.png"
    assert state.favicon_url == "https://example.com/fav.ico"


def test_branding_post_empty_urls_clears_state(authed_client):
    resp = authed_client.post(
        "/wizard/step/8",
        data={
            "site_title": "",
            "logo_light_url": "",
            "logo_dark_url": "",
            "favicon_url": "",
        },
    )
    assert resp.status_code == 200
    state = _get_state(authed_client)
    assert state.site_title == ""
    assert state.logo_light_url == ""
    assert state.logo_dark_url == ""
    assert state.favicon_url == ""


# ---------------------------------------------------------------------------
# 3. POST /wizard/step/8 — file upload paths
# ---------------------------------------------------------------------------


def test_branding_post_logo_light_png_upload_saves_file(authed_client, config_dir: Path):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"logo_light_file": ("logo_light.png", io.BytesIO(_TINY_PNG), "image/png")},
        data={"site_title": ""},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state.logo_light_url.startswith("/wizard/branding/")
    assert state.logo_light_url.endswith(".png")

    saved_path = config_dir / "branding" / Path(state.logo_light_url).name
    assert saved_path.exists()
    assert saved_path.read_bytes() == _TINY_PNG


def test_branding_post_logo_dark_svg_upload_saves_file(authed_client, config_dir: Path):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"logo_dark_file": ("logo_dark.svg", io.BytesIO(_TINY_SVG), "image/svg+xml")},
        data={"site_title": ""},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state.logo_dark_url.startswith("/wizard/branding/")
    assert state.logo_dark_url.endswith(".svg")

    saved_path = config_dir / "branding" / Path(state.logo_dark_url).name
    assert saved_path.exists()


def test_branding_post_favicon_ico_upload_saves_file(authed_client, config_dir: Path):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"favicon_file": ("favicon.ico", io.BytesIO(_TINY_ICO), "image/x-icon")},
        data={"site_title": ""},
    )
    assert resp.status_code == 200

    state = _get_state(authed_client)
    assert state.favicon_url.startswith("/wizard/branding/")
    assert state.favicon_url.endswith(".ico")


def test_branding_post_favicon_png_upload_saves_file(authed_client, config_dir: Path):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"favicon_file": ("favicon.png", io.BytesIO(_TINY_PNG), "image/png")},
        data={"site_title": ""},
    )
    assert resp.status_code == 200
    state = _get_state(authed_client)
    assert state.favicon_url.startswith("/wizard/branding/")


# ---------------------------------------------------------------------------
# 4. POST /wizard/step/8 — file upload takes precedence over URL text input
# ---------------------------------------------------------------------------


def test_branding_post_file_takes_precedence_over_url_text(authed_client, config_dir: Path):
    """When both a file and a URL text value are submitted, the file wins."""
    resp = authed_client.post(
        "/wizard/step/8",
        files={"logo_light_file": ("my_logo.png", io.BytesIO(_TINY_PNG), "image/png")},
        data={
            "site_title": "",
            "logo_light_url": "https://example.com/should_be_ignored.png",
        },
    )
    assert resp.status_code == 200
    state = _get_state(authed_client)
    # The saved URL should be the uploaded file path, not the text-field URL.
    assert state.logo_light_url.startswith("/wizard/branding/")
    assert "should_be_ignored" not in state.logo_light_url


# ---------------------------------------------------------------------------
# 5. POST /wizard/step/8 — wrong extension returns 422
# ---------------------------------------------------------------------------


def test_branding_post_wrong_extension_returns_422_for_logo(authed_client):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"logo_light_file": ("logo.gif", io.BytesIO(b"GIF89a"), "image/gif")},
        data={"site_title": ""},
    )
    assert resp.status_code == 422
    assert "gif" in resp.text.lower() or "Unsupported" in resp.text


def test_branding_post_wrong_extension_returns_422_for_favicon(authed_client):
    resp = authed_client.post(
        "/wizard/step/8",
        files={"favicon_file": ("favicon.webp", io.BytesIO(b"RIFF....WEBP"), "image/webp")},
        data={"site_title": ""},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 6. POST /wizard/step/8 — file exceeding size limit returns 422
# ---------------------------------------------------------------------------


def test_branding_post_logo_exceeds_size_limit_returns_422(authed_client):
    # Create a fake PNG-extension file that is 501 KB.
    big_data = b"\x89PNG\r\n" + b"x" * (501 * 1024)
    resp = authed_client.post(
        "/wizard/step/8",
        files={"logo_light_file": ("big_logo.png", io.BytesIO(big_data), "image/png")},
        data={"site_title": ""},
    )
    assert resp.status_code == 422
    assert "501" in resp.text or "500" in resp.text or "KB" in resp.text or "limit" in resp.text.lower()


def test_branding_post_favicon_exceeds_size_limit_returns_422(authed_client):
    # Create a fake PNG-extension file that is 101 KB.
    big_data = b"\x89PNG\r\n" + b"x" * (101 * 1024)
    resp = authed_client.post(
        "/wizard/step/8",
        files={"favicon_file": ("big_fav.png", io.BytesIO(big_data), "image/png")},
        data={"site_title": ""},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 6b. GET /wizard/step/8 — single-logo inversion advisory (ADR-022)
# ---------------------------------------------------------------------------


def _set_logos(client, *, light: str, dark: str) -> None:
    """Set the two logo URLs on the client's wizard state and persist them."""
    from weewx_clearskies_config.wizard.state import get_wizard_state, save_wizard_state

    cookie = client.cookies.get("clearskies_session")
    state = get_wizard_state(cookie)
    state.logo_light_url = light
    state.logo_dark_url = dark
    save_wizard_state(cookie, state)


def test_branding_warns_when_light_only(authed_client):
    """Light logo present, dark absent → advisory about dark-theme inversion."""
    _set_logos(authed_client, light="https://example.com/light.png", dark="")
    resp = authed_client.get("/wizard/step/8")
    assert resp.status_code == 200
    assert "light-theme logo but no dark-theme logo" in resp.text
    # Non-blocking advisory framing, not an error.
    assert "<strong>Note:</strong>" in resp.text


def test_branding_warns_when_dark_only(authed_client):
    """Dark logo present, light absent → advisory about light-theme inversion."""
    _set_logos(authed_client, light="", dark="https://example.com/dark.png")
    resp = authed_client.get("/wizard/step/8")
    assert resp.status_code == 200
    assert "dark-theme logo but no light-theme logo" in resp.text
    assert "<strong>Note:</strong>" in resp.text


def test_branding_no_warning_when_both_logos_present(authed_client):
    """Both logos present → no inversion advisory."""
    _set_logos(
        authed_client,
        light="https://example.com/light.png",
        dark="https://example.com/dark.png",
    )
    resp = authed_client.get("/wizard/step/8")
    assert resp.status_code == 200
    assert "colour-inverted" not in resp.text


def test_branding_no_warning_when_no_logos(authed_client):
    """Neither logo present → no inversion advisory."""
    _set_logos(authed_client, light="", dark="")
    resp = authed_client.get("/wizard/step/8")
    assert resp.status_code == 200
    assert "colour-inverted" not in resp.text


# ---------------------------------------------------------------------------
# 7. _sanitise_filename — unit tests
# ---------------------------------------------------------------------------


def test_sanitise_filename_strips_path_components():
    from weewx_clearskies_config.wizard.routes import _sanitise_filename

    assert _sanitise_filename("../../etc/passwd") == "passwd"
    assert _sanitise_filename("/etc/shadow") == "shadow"


def test_sanitise_filename_replaces_special_chars():
    from weewx_clearskies_config.wizard.routes import _sanitise_filename

    result = _sanitise_filename("my logo (v2).png")
    assert " " not in result
    assert "(" not in result
    assert result.endswith(".png")


def test_sanitise_filename_preserves_safe_chars():
    from weewx_clearskies_config.wizard.routes import _sanitise_filename

    assert _sanitise_filename("my-logo_v2.png") == "my-logo_v2.png"


def test_sanitise_filename_empty_fallback():
    from weewx_clearskies_config.wizard.routes import _sanitise_filename

    # All unsafe chars stripped → fall back to "upload"
    result = _sanitise_filename("!!!.png")
    assert result  # non-empty

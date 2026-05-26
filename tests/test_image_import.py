"""Tests for weewx_clearskies_config.wizard.image_import (ADR-043).

Covers: detect_image_paths, resolve_images_local, resolve_images_api,
        and the full local-then-API resolution flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from weewx_clearskies_config.wizard.image_import import (
    IMAGE_EXTRAS_KEYS,
    detect_image_paths,
    resolve_images_api,
    resolve_images_local,
)


# ---------------------------------------------------------------------------
# detect_image_paths
# ---------------------------------------------------------------------------


def test_detect_image_paths_extracts_branding_images() -> None:
    """Keys logo_image and favicon in branding are extracted."""
    config: dict[str, Any] = {
        "extras": {
            "branding": {
                "logo_image": "/images/logo.png",
                "favicon": "/images/favicon.ico",
            }
        }
    }
    result = detect_image_paths(config)
    assert result == {
        "logo_image": "/images/logo.png",
        "favicon": "/images/favicon.ico",
    }


def test_detect_image_paths_ignores_non_image_keys() -> None:
    """site_title is a branding key but not an image key — excluded."""
    config: dict[str, Any] = {
        "extras": {
            "branding": {
                "site_title": "My Station",
                "logo_image": "/images/logo.png",
            }
        }
    }
    result = detect_image_paths(config)
    assert "site_title" not in result
    assert "logo_image" in result


def test_detect_image_paths_empty_branding() -> None:
    """No branding section returns empty dict."""
    config: dict[str, Any] = {"extras": {}}
    result = detect_image_paths(config)
    assert result == {}


def test_detect_image_paths_empty_values() -> None:
    """Keys with empty string values are excluded."""
    config: dict[str, Any] = {
        "extras": {
            "branding": {
                "logo_image": "",
                "logo_image_dark": "/images/logo-dark.png",
                "favicon": "",
            }
        }
    }
    result = detect_image_paths(config)
    assert result == {"logo_image_dark": "/images/logo-dark.png"}


# ---------------------------------------------------------------------------
# resolve_images_local
# ---------------------------------------------------------------------------


def test_resolve_local_copies_file(tmp_path: Path) -> None:
    """A file that exists in the skin dir is copied to dest_dir with status 'local'."""
    skin_root = tmp_path / "skins"
    skin_dir = skin_root / "Belchertown" / "images"
    skin_dir.mkdir(parents=True)
    src_file = skin_dir / "logo.png"
    src_file.write_bytes(b"PNG_DATA")

    dest_dir = tmp_path / "branding"
    image_paths = {"logo_image": "/images/logo.png"}

    results = resolve_images_local(image_paths, "Belchertown", dest_dir, skin_root=skin_root)

    assert results["logo_image"]["status"] == "local"
    dest = Path(results["logo_image"]["dest"])
    assert dest.exists()
    assert dest.read_bytes() == b"PNG_DATA"
    assert results["logo_image"]["original"] == "/images/logo.png"


def test_resolve_local_missing_file(tmp_path: Path) -> None:
    """A file not in the skin dir results in status 'unresolved'."""
    skin_root = tmp_path / "skins"
    skin_root.mkdir(parents=True)
    dest_dir = tmp_path / "branding"

    image_paths = {"logo_image": "/images/logo.png"}

    results = resolve_images_local(image_paths, "Belchertown", dest_dir, skin_root=skin_root)

    assert results["logo_image"]["status"] == "unresolved"
    assert results["logo_image"]["dest"] is None
    assert results["logo_image"]["original"] == "/images/logo.png"


def test_resolve_local_creates_dest_dir(tmp_path: Path) -> None:
    """dest_dir is created automatically when a file is found."""
    skin_root = tmp_path / "skins"
    skin_dir = skin_root / "Belchertown"
    skin_dir.mkdir(parents=True)
    src_file = skin_dir / "favicon.ico"
    src_file.write_bytes(b"ICO")

    dest_dir = tmp_path / "new" / "branding"
    assert not dest_dir.exists()

    image_paths = {"favicon": "favicon.ico"}
    resolve_images_local(image_paths, "Belchertown", dest_dir, skin_root=skin_root)

    assert dest_dir.exists()


# ---------------------------------------------------------------------------
# resolve_images_api
# ---------------------------------------------------------------------------


def test_resolve_api_fetches_file(tmp_path: Path) -> None:
    """When api_client.fetch_skin_file returns bytes, file is saved with status 'api'."""
    mock_client = MagicMock()
    mock_client.fetch_skin_file.return_value = b"PNG_FROM_API"

    unresolved: dict[str, Any] = {
        "logo_image": {"status": "unresolved", "dest": None, "original": "/images/logo.png"},
    }
    dest_dir = tmp_path / "branding"

    results = resolve_images_api(unresolved, "Belchertown", dest_dir, mock_client)

    assert results["logo_image"]["status"] == "api"
    dest = Path(results["logo_image"]["dest"])
    assert dest.read_bytes() == b"PNG_FROM_API"
    mock_client.fetch_skin_file.assert_called_once_with("Belchertown", "images/logo.png")


def test_resolve_api_returns_none(tmp_path: Path) -> None:
    """When api_client.fetch_skin_file returns None, status is 'missing'."""
    mock_client = MagicMock()
    mock_client.fetch_skin_file.return_value = None

    unresolved: dict[str, Any] = {
        "favicon": {"status": "unresolved", "dest": None, "original": "/favicon.ico"},
    }
    dest_dir = tmp_path / "branding"

    results = resolve_images_api(unresolved, "Belchertown", dest_dir, mock_client)

    assert results["favicon"]["status"] == "missing"
    assert results["favicon"]["dest"] is None


def test_resolve_api_skips_already_resolved(tmp_path: Path) -> None:
    """Entries with status != 'unresolved' are passed through untouched."""
    mock_client = MagicMock()

    already_resolved: dict[str, Any] = {
        "logo_image": {
            "status": "local",
            "dest": "/some/path/logo.png",
            "original": "/images/logo.png",
        },
    }
    dest_dir = tmp_path / "branding"

    results = resolve_images_api(already_resolved, "Belchertown", dest_dir, mock_client)

    mock_client.fetch_skin_file.assert_not_called()
    assert results["logo_image"]["status"] == "local"
    assert results["logo_image"]["dest"] == "/some/path/logo.png"


def test_resolve_api_handles_exception(tmp_path: Path) -> None:
    """When fetch_skin_file raises, entry is marked 'missing' rather than propagating."""
    mock_client = MagicMock()
    mock_client.fetch_skin_file.side_effect = RuntimeError("network failure")

    unresolved: dict[str, Any] = {
        "logo_image": {"status": "unresolved", "dest": None, "original": "/images/logo.png"},
    }
    dest_dir = tmp_path / "branding"

    results = resolve_images_api(unresolved, "Belchertown", dest_dir, mock_client)

    assert results["logo_image"]["status"] == "missing"
    assert results["logo_image"]["dest"] is None


# ---------------------------------------------------------------------------
# Full flow: local resolution then API for remaining unresolved
# ---------------------------------------------------------------------------


def test_full_flow_local_then_api(tmp_path: Path) -> None:
    """Local-present file resolves via local; missing file resolves via API."""
    skin_root = tmp_path / "skins"
    skin_dir = skin_root / "Belchertown" / "images"
    skin_dir.mkdir(parents=True)
    logo_file = skin_dir / "logo.png"
    logo_file.write_bytes(b"LOGO")

    dest_dir = tmp_path / "branding"

    image_paths = {
        "logo_image": "/images/logo.png",          # exists locally
        "favicon": "/images/favicon.ico",           # missing locally
    }

    # Step 1: local resolution
    local_results = resolve_images_local(
        image_paths, "Belchertown", dest_dir, skin_root=skin_root
    )
    assert local_results["logo_image"]["status"] == "local"
    assert local_results["favicon"]["status"] == "unresolved"

    # Step 2: API resolution for unresolved entries only
    mock_client = MagicMock()
    mock_client.fetch_skin_file.return_value = b"FAVICON_DATA"

    final_results = resolve_images_api(local_results, "Belchertown", dest_dir, mock_client)

    assert final_results["logo_image"]["status"] == "local"   # untouched
    assert final_results["favicon"]["status"] == "api"         # resolved via API

    # Confirm the API was called only for the unresolved favicon, not for logo
    mock_client.fetch_skin_file.assert_called_once_with("Belchertown", "images/favicon.ico")

    favicon_dest = Path(final_results["favicon"]["dest"])
    assert favicon_dest.read_bytes() == b"FAVICON_DATA"

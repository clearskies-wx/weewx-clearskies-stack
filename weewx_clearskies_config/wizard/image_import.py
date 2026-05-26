"""Image import from skin directories (ADR-043).

Detects image paths in imported skin.conf [Extras] branding keys and
resolves them — first from the local filesystem, then via the API.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_EXTRAS_KEYS = frozenset({"logo_image", "logo_image_dark", "favicon"})

DEFAULT_SKIN_ROOT = Path("/etc/weewx/skins")


def detect_image_paths(imported_config: dict[str, Any]) -> dict[str, str]:
    """Extract image file paths from imported skin.conf extras.branding.

    Returns: {key: raw_path} for each branding key that has a non-empty value
    and is an image-related key.
    """
    branding = imported_config.get("extras", {}).get("branding", {})
    return {k: v for k, v in branding.items() if k in IMAGE_EXTRAS_KEYS and v}


def resolve_images_local(
    image_paths: dict[str, str],
    source_skin: str,
    dest_dir: Path,
    skin_root: Path = DEFAULT_SKIN_ROOT,
) -> dict[str, dict[str, Any]]:
    """Try to resolve image paths from the local filesystem.

    Args:
        image_paths: {key: raw_path} from detect_image_paths
        source_skin: Name of the source skin (e.g. "Belchertown")
        dest_dir: Where to copy resolved images
        skin_root: Root of weewx skins directory

    Returns: {key: {"status": "local"|"unresolved", "dest": Path|None, "original": str}}
    """
    results: dict[str, dict[str, Any]] = {}

    for key, raw_path in image_paths.items():
        rel_path = raw_path.lstrip("/")
        source = skin_root / source_skin / rel_path

        if source.is_file():
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / Path(rel_path).name
            shutil.copy2(source, dest)
            results[key] = {"status": "local", "dest": str(dest), "original": raw_path}
            logger.info("Imported %s from local: %s", key, source)
        else:
            results[key] = {"status": "unresolved", "dest": None, "original": raw_path}

    return results


def resolve_images_api(
    unresolved: dict[str, dict[str, Any]],
    source_skin: str,
    dest_dir: Path,
    api_client: Any,
) -> dict[str, dict[str, Any]]:
    """Try to resolve unresolved images via the API.

    Args:
        unresolved: Results dict from resolve_images_local (only processes "unresolved" entries)
        source_skin: Source skin name
        dest_dir: Where to save fetched images
        api_client: ApiClient instance (must have fetch_skin_file method)

    Returns: Updated results dict with resolved entries changed to "api" status
    """
    results = dict(unresolved)

    for key, info in results.items():
        if info["status"] != "unresolved":
            continue

        raw_path = info["original"]
        rel_path = raw_path.lstrip("/")

        try:
            data = api_client.fetch_skin_file(source_skin, rel_path)
        except Exception:  # noqa: BLE001
            data = None

        if data:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / Path(rel_path).name
            dest.write_bytes(data)
            results[key] = {"status": "api", "dest": str(dest), "original": raw_path}
            logger.info("Imported %s from API: %s/%s", key, source_skin, rel_path)
        else:
            results[key] = {"status": "missing", "dest": None, "original": raw_path}
            logger.warning("Could not resolve %s: %s", key, raw_path)

    return results

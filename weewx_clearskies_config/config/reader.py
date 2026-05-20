"""Read and parse existing .conf files for the config CRUD UI.

Uses ConfigObj to parse the MANAGED REGION of each component config.
The free-form region below the MANAGED REGION END marker is ignored —
only the managed section is surfaced to the edit UI.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

from configobj import ConfigObj  # type: ignore[import-untyped]

# Marker strings must match config_writer.py and updater.py
_REGION_BEGIN = "# MANAGED REGION BEGIN"
_REGION_END = "# MANAGED REGION END"

COMPONENTS = ("api", "realtime", "stack")


def find_config_dir() -> Path:
    """Return the weewx-clearskies config directory.

    Search order mirrors auth._config_dir():
      1. WEEWX_CLEARSKIES_CONFIG_DIR env var
      2. /etc/weewx-clearskies (system install)
      3. ~/.config/weewx-clearskies (user install)
    """
    env_dir = os.environ.get("WEEWX_CLEARSKIES_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    system_dir = Path("/etc/weewx-clearskies")
    if system_dir.exists():
        return system_dir
    return Path.home() / ".config" / "weewx-clearskies"


def _extract_managed_text(file_text: str) -> str:
    """Return the text of the MANAGED REGION, or the entire file if no markers found.

    Backward compat: hand-written configs without markers are treated as fully managed.
    """
    begin_idx = file_text.find(_REGION_BEGIN)
    end_idx = file_text.find(_REGION_END)

    if begin_idx == -1 or end_idx == -1:
        # No markers — entire file is managed
        return file_text

    # Extract text between begin marker and end marker (exclusive of both marker lines)
    between = file_text[begin_idx + len(_REGION_BEGIN):]
    end_rel = between.find(_REGION_END)
    if end_rel == -1:
        return file_text
    managed = between[:end_rel]
    return managed


def read_config(component: str, config_dir: Path) -> ConfigObj | None:
    """Read <component>.conf if it exists, return parsed ConfigObj of managed region.

    Returns None if the file does not exist.
    """
    if component not in COMPONENTS:
        raise ValueError(f"Unknown component: {component!r}. Must be one of {COMPONENTS}")

    conf_path = config_dir / f"{component}.conf"
    if not conf_path.exists():
        return None

    file_text = conf_path.read_text(encoding="utf-8")
    managed_text = _extract_managed_text(file_text)

    cfg = ConfigObj(infile=io.StringIO(managed_text))
    return cfg


def get_section(
    component: str,
    section_path: str,
    config_dir: Path,
) -> dict[str, Any]:
    """Return the key-value dict for one section (or nested section).

    ``section_path`` supports dot-separated nesting, e.g. ``"forecast.openmeteo"``.
    Returns an empty dict if the component file or section does not exist.
    """
    cfg = read_config(component, config_dir)
    if cfg is None:
        return {}

    # Navigate nested section path
    current: Any = cfg
    for part in section_path.split("."):
        if not isinstance(current, (ConfigObj, dict)) or part not in current:
            return {}
        current = current[part]

    if not isinstance(current, (ConfigObj, dict)):
        return {}

    # Return only scalar values (not nested sub-sections) as strings
    return {k: str(v) for k, v in current.items() if isinstance(v, str)}


def get_all_sections(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Return all sections across all component configs.

    Grouped by component: ``{"api": {"server": {...}, ...}, "realtime": {...}, ...}``
    Top-level sections only — does not recurse into nested sub-sections.
    """
    result: dict[str, dict[str, Any]] = {}

    for component in COMPONENTS:
        cfg = read_config(component, config_dir)
        if cfg is None:
            result[component] = {}
            continue

        sections: dict[str, Any] = {}
        for section_name, section_data in cfg.items():
            if isinstance(section_data, (ConfigObj, dict)):
                sections[section_name] = {
                    k: str(v)
                    for k, v in section_data.items()
                    if isinstance(v, str)
                }
        result[component] = sections

    return result


def get_column_mapping(config_dir: Path) -> dict[str, str | None]:
    """Read [column_mapping] from api.conf.

    Returns dict: db_column_name -> canonical_name (or None if unmapped).
    Returns empty dict if api.conf does not exist or has no column_mapping section.
    """
    cfg = read_config("api", config_dir)
    if cfg is None:
        return {}

    mapping_section = cfg.get("column_mapping", {})
    if not isinstance(mapping_section, (ConfigObj, dict)):
        return {}

    result: dict[str, str | None] = {}
    for db_col, canonical in mapping_section.items():
        if isinstance(canonical, str) and canonical.strip():
            result[db_col] = canonical.strip()
        else:
            result[db_col] = None

    return result

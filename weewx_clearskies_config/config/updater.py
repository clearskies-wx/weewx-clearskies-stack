"""MANAGED REGION merge logic for .conf files and secrets.env updates.

The MANAGED REGION format (written by config_writer.py):

    # Managed by weewx-clearskies-config on YYYY-MM-DD.
    # MANAGED REGION BEGIN
    [section]
    key = value
    # MANAGED REGION END
    # Free-form region below — the configuration UI does not touch this.

update_managed_region() finds the markers, parses the managed block via
ConfigObj, updates the target section, re-serialises, and splices the new
text back in — the free-form region is never touched.
"""

from __future__ import annotations

import io
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from configobj import ConfigObj  # type: ignore[import-untyped]

MANAGED_BEGIN = "# MANAGED REGION BEGIN"
MANAGED_END = "# MANAGED REGION END"
_MANAGED_HEADER_PREFIX = "# Managed by weewx-clearskies-config on "
_FREE_FORM_NOTE = "# Free-form region below — the configuration UI does not touch this.\n"


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _serialize_configobj(cfg: ConfigObj) -> str:
    """Serialize a ConfigObj to a string."""
    buf = io.StringIO()
    cfg.write(fileobject=buf)
    return buf.getvalue()


def update_managed_region(
    config_path: Path,
    section: str,
    values: dict[str, Any],
) -> None:
    """Update one section in the MANAGED REGION of *config_path*.

    Algorithm:
    1. Read existing file as text.
    2. Find MANAGED REGION BEGIN / END markers.
    3. Parse the managed region as ConfigObj.
    4. Update the target section with new values (replaces existing keys,
       does not remove keys the caller omits — use explicit empty string to clear).
    5. Re-serialize the managed region.
    6. Replace managed text in original, preserving everything outside markers.
    7. Write back.

    If no markers are found, the entire file is treated as managed (backward
    compat with hand-written configs).

    Raises:
        FileNotFoundError: config_path does not exist.
        ValueError: section name is empty or contains only whitespace.
    """
    if not section or not section.strip():
        raise ValueError("section must be a non-empty string")

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    file_text = config_path.read_text(encoding="utf-8")

    begin_idx = file_text.find(MANAGED_BEGIN)
    end_idx = file_text.find(MANAGED_END)

    no_markers = begin_idx == -1 or end_idx == -1

    if no_markers:
        # Treat entire file as managed — parse directly
        managed_text = file_text
        pre_text = ""
        post_text = ""
        begin_line_end = -1  # unused
        end_line_start = -1  # unused
    else:
        # Find end of the BEGIN marker line
        begin_line_end = file_text.find("\n", begin_idx)
        if begin_line_end == -1:
            begin_line_end = len(file_text)
        else:
            begin_line_end += 1  # include the newline

        # Find start of the END marker line
        end_line_start = end_idx

        managed_text = file_text[begin_line_end:end_line_start]
        pre_text = file_text[:begin_line_end]
        post_text = file_text[end_line_start:]

    # Parse the managed region
    cfg = ConfigObj(infile=io.StringIO(managed_text))

    # Update (or create) the target section
    if section not in cfg:
        cfg[section] = {}

    target = cfg[section]
    if not isinstance(target, (ConfigObj, dict)):
        cfg[section] = {}
        target = cfg[section]

    for key, val in values.items():
        target[key] = str(val) if val is not None else ""

    # Re-serialize
    new_managed_text = _serialize_configobj(cfg)

    # Rebuild full file
    if no_markers:
        # Update managed header date if present, then write new content
        new_full = (
            f"{_MANAGED_HEADER_PREFIX}{_today()}.\n"
            f"{MANAGED_BEGIN}\n"
            f"{new_managed_text}"
            f"{MANAGED_END}\n"
            f"{_FREE_FORM_NOTE}"
        )
    else:
        # Splice: preserve pre_text (includes BEGIN marker), then new managed content,
        # then post_text (starts at END marker line)
        new_full = pre_text + new_managed_text + post_text

    config_path.write_text(new_full, encoding="utf-8")


def update_secrets(
    key: str,
    value: str,
    config_dir: Path,
) -> None:
    """Update or add a key in secrets.env.

    Reads the existing secrets.env, replaces the value for *key* if present
    or appends it, then writes back with mode 0600.

    Raises:
        ValueError: key is empty or contains whitespace or '='.
    """
    if not key or "=" in key or " " in key or "\t" in key or "\n" in key:
        raise ValueError(f"Invalid secrets key: {key!r}")

    secrets_path = config_dir / "secrets.env"
    config_dir.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if secrets_path.exists():
        existing_lines = secrets_path.read_text(encoding="utf-8").splitlines(keepends=True)

    new_lines: list[str] = []
    found = False
    for line in existing_lines:
        stripped = line.rstrip("\n")
        if stripped.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    secrets_path.write_text("".join(new_lines), encoding="utf-8")
    try:
        secrets_path.chmod(0o600)
    except NotImplementedError:
        # Windows does not support POSIX chmod
        pass


def update_column_mapping(
    mapping: dict[str, str | None],
    config_dir: Path,
) -> None:
    """Update the [column_mapping] section in api.conf via managed region merge.

    This takes effect on the next API request — the API's ColumnRegistry
    re-reads the mapping on config change without requiring a restart.

    Only columns with a non-None canonical name are written; None values
    indicate "leave unmapped" and are omitted from the section.

    Raises:
        FileNotFoundError: api.conf does not exist in config_dir.
    """
    api_conf = config_dir / "api.conf"
    if not api_conf.exists():
        raise FileNotFoundError(f"api.conf not found in config directory: {config_dir}")

    # Filter out None values — only write explicit mappings
    clean_mapping: dict[str, Any] = {
        db_col: canonical
        for db_col, canonical in mapping.items()
        if canonical is not None and str(canonical).strip()
    }

    update_managed_region(api_conf, "column_mapping", clean_mapping)

"""Generate ConfigObj .conf files and secrets.env from WizardState.

All generated .conf files use MANAGED REGION markers so the configuration UI
can update them without touching operator-added free-form config below the
marker.  Secrets are written to a separate secrets.env file (mode 0600) and
are never embedded in .conf files.

MANAGED REGION format:
    # Managed by weewx-clearskies-config on YYYY-MM-DD.
    # MANAGED REGION BEGIN
    ... generated config ...
    # MANAGED REGION END
    # Free-form region below — the configuration UI does not touch this.
"""

from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from configobj import ConfigObj  # type: ignore[import-untyped]

from weewx_clearskies_config.wizard.state import WizardState

_MANAGED_HEADER = "# Managed by weewx-clearskies-config on {date}.\n"
_REGION_BEGIN = "# MANAGED REGION BEGIN\n"
_REGION_END = "# MANAGED REGION END\n"
_FREE_FORM_NOTE = "# Free-form region below — the configuration UI does not touch this.\n"


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _wrap_with_managed_region(cfg: ConfigObj) -> str:
    """Serialize *cfg* and wrap it in MANAGED REGION markers."""
    import io

    buf = io.StringIO()
    cfg.write(outfile=buf)
    content = buf.getvalue()

    lines = [
        _MANAGED_HEADER.format(date=_today()),
        _REGION_BEGIN,
        content,
        _REGION_END,
        _FREE_FORM_NOTE,
    ]
    return "".join(lines)


def _write_file(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


def write_api_conf(state: WizardState, config_dir: Path) -> Path:
    """Write api.conf from *state*.

    Sections written:
      [server]       — bind address and port
      [database]     — DB connection parameters (no password; goes in secrets.env)
      [column_mapping] — operator-confirmed column mappings
      [forecast]     — selected forecast provider
      [alerts]       — selected alerts provider
      [aqi]          — selected AQI provider
      [earthquakes]  — selected earthquakes provider
      [radar]        — selected radar provider

    Returns the path to the written file.
    """
    cfg = ConfigObj()

    cfg["server"] = {
        "bind_host": state.api_bind_host,
        "bind_port": str(state.api_bind_port),
    }

    cfg["database"] = {
        "host": state.db_host or "",
        "port": str(state.db_port),
        "user": state.db_user or "",
        # Password comes from secrets.env — do NOT write it here.
        "name": state.db_name,
    }

    # Write column mappings for non-stock columns only (stock columns
    # auto-map at API startup; only overrides / unmapped need explicit entries).
    mapping_section: dict[str, str] = {}
    for db_col, canonical in state.column_mapping.items():
        if canonical is not None:
            mapping_section[db_col] = canonical
    cfg["column_mapping"] = mapping_section

    # Provider selections — one entry per domain.
    for domain in ("forecast", "alerts", "aqi", "earthquakes", "radar"):
        provider_id = state.providers.get(domain, "")
        cfg[domain] = {"provider": provider_id}

    content = _wrap_with_managed_region(cfg)
    dest = config_dir / "api.conf"
    _write_file(dest, content)
    return dest


def write_realtime_conf(state: WizardState, config_dir: Path) -> Path:
    """Write realtime.conf from *state*.

    Sections written:
      [server]  — bind address and port for the realtime WebSocket service
      [mqtt]    — placeholder for future MQTT configuration

    Returns the path to the written file.
    """
    cfg = ConfigObj()

    cfg["server"] = {
        "bind_host": state.realtime_bind_host,
        "bind_port": str(state.realtime_bind_port),
    }

    # Placeholder MQTT section — operators may need to configure this manually.
    cfg["mqtt"] = {
        "enabled": "false",
        "broker": "",
        "port": "1883",
        "topic": "weather/clearskies",
    }

    content = _wrap_with_managed_region(cfg)
    dest = config_dir / "realtime.conf"
    _write_file(dest, content)
    return dest


def write_stack_conf(state: WizardState, config_dir: Path) -> Path:
    """Write stack.conf from *state*.

    Sections written:
      [ui]  — station display settings

    Returns the path to the written file.
    """
    cfg = ConfigObj()

    cfg["ui"] = {
        "station_name": state.station_name or "",
        "latitude": str(state.latitude) if state.latitude is not None else "",
        "longitude": str(state.longitude) if state.longitude is not None else "",
        "altitude_meters": (
            str(state.altitude_meters) if state.altitude_meters is not None else ""
        ),
        "timezone": state.timezone or "",
        "topology": state.topology,
    }

    content = _wrap_with_managed_region(cfg)
    dest = config_dir / "stack.conf"
    _write_file(dest, content)
    return dest


def write_secrets_env(state: WizardState, config_dir: Path) -> Path:
    """Write secrets.env with provider API keys and the proxy secret.

    Format: ``WEEWX_CLEARSKIES_<DOMAIN>_<PROVIDER>_<FIELD>=<value>``
    The DB password is also written here.

    The file is written with mode 0600 (owner read/write only).
    Returns the path to the written file.
    """
    lines = [
        "# weewx-clearskies secrets — do not commit this file to version control.\n",
        "# Generated by the setup wizard. Managed by weewx-clearskies-config.\n",
        "\n",
    ]

    # DB password
    if state.db_password:
        lines.append(f"WEEWX_CLEARSKIES_DB_PASSWORD={state.db_password}\n")

    # Proxy secret (cross-host topology only)
    if state.proxy_secret:
        lines.append(f"WEEWX_CLEARSKIES_PROXY_SECRET={state.proxy_secret}\n")

    # Provider API keys: WEEWX_CLEARSKIES_<DOMAIN>_<PROVIDER>_<FIELD>=<value>
    for domain, provider_id in state.providers.items():
        creds = state.api_keys.get(provider_id, {})
        for field_name, value in creds.items():
            env_key = (
                f"WEEWX_CLEARSKIES"
                f"_{domain.upper()}"
                f"_{provider_id.upper()}"
                f"_{field_name.upper()}"
            )
            lines.append(f"{env_key}={value}\n")

    content = "".join(lines)
    dest = config_dir / "secrets.env"
    _write_file(dest, content, mode=0o600)

    # Verify the mode was set (Linux/macOS only; Windows ignores chmod).
    try:
        actual_mode = stat.S_IMODE(os.stat(dest).st_mode)
        if actual_mode != 0o600:
            import logging
            logging.getLogger(__name__).warning(
                "Could not set secrets.env to mode 0600; actual mode: %o",
                actual_mode,
            )
    except OSError:
        pass

    return dest


def apply_wizard(state: WizardState, config_dir: Path) -> dict[str, Any]:
    """Write all config files and secrets.env from *state*.

    Orchestrates calls to all write_* functions.  Returns a summary dict:
      {
        "files_written": [<path>, ...],
        "secrets_written": [<path>, ...],
      }
    """
    files_written = []
    secrets_written = []

    files_written.append(str(write_api_conf(state, config_dir)))
    files_written.append(str(write_realtime_conf(state, config_dir)))
    files_written.append(str(write_stack_conf(state, config_dir)))
    secrets_written.append(str(write_secrets_env(state, config_dir)))

    return {
        "files_written": files_written,
        "secrets_written": secrets_written,
    }

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

    buf = io.BytesIO()
    cfg.write(outfile=buf)
    content = buf.getvalue().decode("utf-8")

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
      [input]   — input mode; if mqtt, includes nested [[mqtt]] subsection

    The MQTT password is never written here — only the env var name
    (WEEWX_CLEARSKIES_MQTT_PASSWORD) is stored, and the password itself
    goes into secrets.env.

    Returns the path to the written file.
    """
    cfg = ConfigObj()

    cfg["server"] = {
        "bind_host": state.realtime_bind_host,
        "bind_port": str(state.realtime_bind_port),
    }

    if state.input_mode == "mqtt":
        cfg["input"] = {"mode": "mqtt"}
        cfg["input"]["mqtt"] = {
            "broker_host": state.mqtt_broker_host,
            "broker_port": str(state.mqtt_broker_port),
            "topic": state.mqtt_topic,
            "client_id": state.mqtt_client_id,
            "username": state.mqtt_username,
            # Store the env var name, never the password value.
            "password_env": "WEEWX_CLEARSKIES_MQTT_PASSWORD",
            "tls": "true" if state.mqtt_tls else "false",
            "ca_file": "",
            "qos": str(state.mqtt_qos),
            "keepalive": str(state.mqtt_keepalive),
        }
    else:
        cfg["input"] = {"mode": "direct"}

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


def _shell_quote_value(value: str) -> str:
    """Wrap *value* in single quotes for safe use in a POSIX shell env file.

    Single-quoting is the safest quoting style for values that may contain
    spaces, dollar signs, backslashes, or other shell-special characters.
    The only character that cannot appear inside single quotes is a literal
    single quote; we escape it via the '' sequence (end quote, literal
    apostrophe, re-open quote).
    """
    return "'" + value.replace("'", "'\\''") + "'"


def write_secrets_env(state: WizardState, config_dir: Path) -> Path:
    """Write secrets.env with provider API keys and the proxy secret.

    Format: ``WEEWX_CLEARSKIES_<DOMAIN>_<PROVIDER>_<FIELD>='<value>'``
    All values are single-quoted so shell special characters are safe.
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
        lines.append(f"WEEWX_CLEARSKIES_DB_PASSWORD={_shell_quote_value(state.db_password)}\n")

    # Proxy secret (cross-host topology only)
    if state.proxy_secret:
        lines.append(f"WEEWX_CLEARSKIES_PROXY_SECRET={_shell_quote_value(state.proxy_secret)}\n")

    # MQTT password — written only when mqtt mode is active and a password is set.
    if state.input_mode == "mqtt" and state.mqtt_password:
        lines.append(f"WEEWX_CLEARSKIES_MQTT_PASSWORD={_shell_quote_value(state.mqtt_password)}\n")

    # Provider API keys: WEEWX_CLEARSKIES_<DOMAIN>_<PROVIDER>_<FIELD>='<value>'
    for domain, provider_id in state.providers.items():
        creds = state.api_keys.get(provider_id, {})
        for field_name, value in creds.items():
            env_key = (
                f"WEEWX_CLEARSKIES"
                f"_{domain.upper()}"
                f"_{provider_id.upper()}"
                f"_{field_name.upper()}"
            )
            lines.append(f"{env_key}={_shell_quote_value(value)}\n")

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


def write_bootstrap_summary(
    state: WizardState,
    result: dict[str, Any],
    config_dir: Path,
) -> Path:
    """Write a human-readable bootstrap-summary.md next to the generated configs.

    Contents:
      - Date the wizard ran
      - List of files written
      - Proxy secret reminder (cross-host topology only)
      - Copy-to-server instructions

    Returns the path to the written file.
    """
    lines = [
        "# Clear Skies — Bootstrap Summary\n",
        "\n",
        f"Generated: {_today()}\n",
        "\n",
        "## Files written\n",
        "\n",
    ]

    for path in result.get("files_written", []):
        lines.append(f"- `{path}`\n")
    for path in result.get("secrets_written", []):
        lines.append(f"- `{path}` (mode 0600 — secrets)\n")

    if state.proxy_secret and state.topology == "cross-host":
        lines += [
            "\n",
            "## Proxy secret (cross-host topology)\n",
            "\n",
            "A shared proxy secret was generated.  Copy it to both the API host and\n",
            "the realtime host so the HMAC validation succeeds:\n",
            "\n",
            "```\n",
            f"WEEWX_CLEARSKIES_PROXY_SECRET=<value in secrets.env>\n",
            "```\n",
            "\n",
            "See `secrets.env` for the actual value.  Do not commit that file.\n",
        ]

    lines += [
        "\n",
        "## Copy instructions\n",
        "\n",
        "Copy the generated files to your server:\n",
        "\n",
        "```sh\n",
        f"scp {config_dir}/api.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/realtime.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/stack.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/secrets.env user@server:/etc/weewx-clearskies/\n",
        "```\n",
        "\n",
        "Ensure `secrets.env` is chmod 0600 on the target server.\n",
    ]

    dest = config_dir / "bootstrap-summary.md"
    _write_file(dest, "".join(lines))
    return dest


def apply_wizard(state: WizardState, config_dir: Path) -> dict[str, Any]:
    """Write all config files and secrets.env from *state*.

    Orchestrates calls to all write_* functions.  Returns a summary dict:
      {
        "files_written": [<path>, ...],
        "secrets_written": [<path>, ...],
        "summary_path": "<path>",
      }
    """
    files_written = []
    secrets_written = []

    files_written.append(str(write_api_conf(state, config_dir)))
    files_written.append(str(write_realtime_conf(state, config_dir)))
    files_written.append(str(write_stack_conf(state, config_dir)))
    secrets_written.append(str(write_secrets_env(state, config_dir)))

    result: dict[str, Any] = {
        "files_written": files_written,
        "secrets_written": secrets_written,
    }

    summary_path = write_bootstrap_summary(state, result, config_dir)
    result["summary_path"] = str(summary_path)

    return result

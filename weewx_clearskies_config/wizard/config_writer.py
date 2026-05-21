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
    """Write secrets.env with local service secrets.

    Writes only secrets consumed by local services (realtime, stack).
    Database passwords and provider API keys are sent to the API via
    POST /setup/apply and are managed in the API's own secrets.env.

    Local secrets written:
      - WEEWX_CLEARSKIES_PROXY_SECRET (shared with API for HMAC validation;
        also written by the API — both sides need the same value)
      - WEEWX_CLEARSKIES_MQTT_PASSWORD (consumed by the realtime service)

    Not written here:
      - WEEWX_CLEARSKIES_DB_PASSWORD (managed by the API)
      - Provider API keys (managed by the API)
      - WEEWX_CLEARSKIES_BOOTSTRAP_TOKEN (one-time token; already consumed)

    The file is written with mode 0600 (owner read/write only).
    Returns the path to the written file.
    """
    lines = [
        "# weewx-clearskies secrets — do not commit this file to version control.\n",
        "# Generated by the setup wizard. Managed by weewx-clearskies-config.\n",
        "# Database password and provider API keys are stored in the API's secrets.env.\n",
        "\n",
    ]

    # Proxy secret (cross-host topology only).  The API also writes this value
    # to its own secrets.env; both sides must have the same value.
    if state.proxy_secret:
        lines.append(f"WEEWX_CLEARSKIES_PROXY_SECRET={_shell_quote_value(state.proxy_secret)}\n")

    # MQTT password — consumed by the realtime service; only written when mqtt
    # mode is active and a password is set.
    if state.input_mode == "mqtt" and state.mqtt_password:
        lines.append(f"WEEWX_CLEARSKIES_MQTT_PASSWORD={_shell_quote_value(state.mqtt_password)}\n")

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
        "Copy the local config files to the stack host (api.conf is written by the API itself):\n",
        "\n",
        "```sh\n",
        f"scp {config_dir}/realtime.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/stack.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/secrets.env user@server:/etc/weewx-clearskies/\n",
        "```\n",
        "\n",
        "Ensure `secrets.env` is chmod 0600 on the target server.\n",
        "Restart the API on the weewx host to load the configuration it received during setup.\n",
        "Restart the realtime service to apply realtime.conf.\n",
    ]

    dest = config_dir / "bootstrap-summary.md"
    _write_file(dest, "".join(lines))
    return dest


def apply_wizard(state: WizardState, config_dir: Path) -> dict[str, Any]:
    """Write local config files and secrets.env from *state*.

    api.conf is written by the API itself when the wizard sends the apply
    payload via POST /setup/apply (ADR-038).  This function writes only the
    locally-consumed config files.

    Orchestrates calls to write_realtime_conf, write_stack_conf, and
    write_secrets_env.  Returns a summary dict:
      {
        "files_written": [<path>, ...],
        "secrets_written": [<path>, ...],
        "summary_path": "<path>",
      }
    """
    files_written = []
    secrets_written = []

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

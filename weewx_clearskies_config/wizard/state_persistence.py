"""Wizard progress persistence: save/load/delete progress files on disk.

Progress files allow wizard sessions to survive tool restarts.  Secrets are
never stored in progress files — passwords and API keys are replaced with a
sentinel before serializing and re-read from secrets.env on load.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from weewx_clearskies_config.wizard.state import WizardState

logger = logging.getLogger(__name__)

_SECRET_SENTINEL = "__FROM_SECRETS__"

# Domains used to reconstruct secrets.env key names for API keys.
_PROVIDER_DOMAINS = ("forecast", "alerts", "aqi", "earthquakes", "radar")


def _progress_path(session_id: str, config_dir: Path) -> Path:
    hashed = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return config_dir / f"wizard_progress_{hashed}.json"


def _read_secrets_env(config_dir: Path) -> dict[str, str]:
    secrets_path = config_dir / "secrets.env"
    if not secrets_path.exists():
        return {}
    result: dict[str, str] = {}
    try:
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    except OSError:
        pass
    return result


def save_progress(session_id: str, state: WizardState, config_dir: Path) -> None:
    """Serialize WizardState to a JSON progress file. Atomic write.

    db_password and api_keys values are replaced with _SECRET_SENTINEL so
    secrets are never written to disk outside of secrets.env.
    """
    raw = dataclasses.asdict(state)

    if raw.get("db_password") is not None:
        raw["db_password"] = _SECRET_SENTINEL

    scrubbed_api_keys: dict[str, dict[str, str]] = {}
    for provider_id, creds in raw.get("api_keys", {}).items():
        scrubbed_api_keys[provider_id] = {k: _SECRET_SENTINEL for k in creds}
    raw["api_keys"] = scrubbed_api_keys

    if raw.get("proxy_secret") is not None:
        raw["proxy_secret"] = _SECRET_SENTINEL

    raw["_saved_at"] = time.time()

    config_dir.mkdir(parents=True, exist_ok=True)
    dest = _progress_path(session_id, config_dir)
    tmp = dest.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        os.replace(tmp, dest)
    except OSError as exc:
        logger.warning("Could not save wizard progress: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def load_progress(session_id: str, config_dir: Path) -> WizardState | None:
    """Load wizard progress from disk. Returns None if missing or corrupt.

    Sentineled secrets are re-read from secrets.env on load.
    """
    path = _progress_path(session_id, config_dir)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Corrupt wizard progress file %s: %s", path.name, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("Wizard progress file %s is not a JSON object", path.name)
        return None

    raw.pop("_saved_at", None)

    secrets = _read_secrets_env(config_dir)

    if raw.get("db_password") == _SECRET_SENTINEL:
        raw["db_password"] = secrets.get("WEEWX_CLEARSKIES_DB_PASSWORD")

    if raw.get("proxy_secret") == _SECRET_SENTINEL:
        raw["proxy_secret"] = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")

    providers: dict[str, str] = raw.get("providers", {}) if isinstance(raw.get("providers"), dict) else {}
    api_keys: dict[str, dict[str, str]] = {}
    raw_api_keys = raw.get("api_keys", {})
    if isinstance(raw_api_keys, dict):
        for provider_id, creds in raw_api_keys.items():
            if not isinstance(creds, dict):
                continue
            restored: dict[str, str] = {}
            for field_name, val in creds.items():
                if val == _SECRET_SENTINEL:
                    domain = _domain_for_provider(provider_id, providers)
                    if domain:
                        env_key = (
                            f"WEEWX_CLEARSKIES"
                            f"_{domain.upper()}"
                            f"_{provider_id.upper()}"
                            f"_{field_name.upper()}"
                        )
                        restored[field_name] = secrets.get(env_key, "")
                    else:
                        restored[field_name] = ""
                elif isinstance(val, str):
                    restored[field_name] = val
            api_keys[provider_id] = restored
    raw["api_keys"] = api_keys

    try:
        return _state_from_dict(raw)
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning("Could not reconstruct WizardState from %s: %s", path.name, exc)
        return None


def delete_progress(session_id: str, config_dir: Path) -> None:
    """Remove the progress file for *session_id* (called after successful apply)."""
    path = _progress_path(session_id, config_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not delete wizard progress file %s: %s", path.name, exc)


def cleanup_stale_progress(config_dir: Path, max_age_hours: int = 72) -> None:
    """Remove progress files older than *max_age_hours*."""
    cutoff = time.time() - max_age_hours * 3600
    try:
        for path in config_dir.glob("wizard_progress_*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                saved_at = raw.get("_saved_at", 0)
                if isinstance(saved_at, (int, float)) and saved_at < cutoff:
                    path.unlink(missing_ok=True)
                    logger.info("Removed stale wizard progress file: %s", path.name)
            except (OSError, json.JSONDecodeError):
                pass
    except OSError as exc:
        logger.warning("Could not scan config_dir for stale progress files: %s", exc)


def populate_from_config(config_dir: Path) -> WizardState:
    """Build a WizardState from existing config files.

    Reads api.conf, stack.conf, realtime.conf, and secrets.env if they exist.
    Returns a WizardState with whatever fields could be populated; fields that
    cannot be read remain at their dataclass defaults.
    """
    from weewx_clearskies_config.config.reader import read_config

    state = WizardState()
    secrets = _read_secrets_env(config_dir)

    api_cfg = read_config("api", config_dir)
    if api_cfg is not None:
        db_section = api_cfg.get("database", {})
        if isinstance(db_section, dict):
            if db_section.get("host"):
                state.db_host = str(db_section["host"])
            if db_section.get("port"):
                try:
                    state.db_port = int(db_section["port"])
                except (ValueError, TypeError):
                    pass
            if db_section.get("user"):
                state.db_user = str(db_section["user"])
            if db_section.get("name"):
                state.db_name = str(db_section["name"])

        state.db_password = secrets.get("WEEWX_CLEARSKIES_DB_PASSWORD")

        mapping_section = api_cfg.get("column_mapping", {})
        if isinstance(mapping_section, dict):
            state.column_mapping = {
                k: (str(v) if v else None) for k, v in mapping_section.items()
            }

        providers: dict[str, str] = {}
        for domain in _PROVIDER_DOMAINS:
            domain_section = api_cfg.get(domain, {})
            if isinstance(domain_section, dict):
                provider_id = str(domain_section.get("provider", "")).strip()
                if provider_id:
                    providers[domain] = provider_id
        state.providers = providers

        server_section = api_cfg.get("server", {})
        if isinstance(server_section, dict):
            if server_section.get("bind_host"):
                state.api_bind_host = str(server_section["bind_host"])
            if server_section.get("bind_port"):
                try:
                    state.api_bind_port = int(server_section["bind_port"])
                except (ValueError, TypeError):
                    pass

    stack_cfg = read_config("stack", config_dir)
    if stack_cfg is not None:
        ui_section = stack_cfg.get("ui", {})
        if isinstance(ui_section, dict):
            if ui_section.get("station_name"):
                state.station_name = str(ui_section["station_name"])
            if ui_section.get("latitude"):
                try:
                    state.latitude = float(ui_section["latitude"])
                except (ValueError, TypeError):
                    pass
            if ui_section.get("longitude"):
                try:
                    state.longitude = float(ui_section["longitude"])
                except (ValueError, TypeError):
                    pass
            if ui_section.get("altitude_meters"):
                try:
                    state.altitude_meters = float(ui_section["altitude_meters"])
                except (ValueError, TypeError):
                    pass
            if ui_section.get("timezone"):
                state.timezone = str(ui_section["timezone"])
            if ui_section.get("topology") in ("same-host", "cross-host"):
                state.topology = str(ui_section["topology"])

    realtime_cfg = read_config("realtime", config_dir)
    if realtime_cfg is not None:
        server_section = realtime_cfg.get("server", {})
        if isinstance(server_section, dict):
            if server_section.get("bind_host"):
                state.realtime_bind_host = str(server_section["bind_host"])
            if server_section.get("bind_port"):
                try:
                    state.realtime_bind_port = int(server_section["bind_port"])
                except (ValueError, TypeError):
                    pass

    state.proxy_secret = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")

    if state.providers:
        api_keys: dict[str, dict[str, str]] = {}
        for domain, provider_id in state.providers.items():
            existing_creds = api_keys.get(provider_id, {})
            env_prefix = (
                f"WEEWX_CLEARSKIES_{domain.upper()}_{provider_id.upper()}_"
            )
            for env_key, env_val in secrets.items():
                if env_key.startswith(env_prefix):
                    field_name = env_key[len(env_prefix):].lower()
                    existing_creds[field_name] = env_val
            if existing_creds:
                api_keys[provider_id] = existing_creds
        state.api_keys = api_keys

    return state


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _domain_for_provider(provider_id: str, providers: dict[str, str]) -> str | None:
    """Return the domain key that maps to *provider_id*, or None."""
    for domain, pid in providers.items():
        if pid == provider_id:
            return domain
    return None


def _state_from_dict(raw: dict[str, Any]) -> WizardState:
    """Construct a WizardState from a plain dict, validating types."""
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(WizardState):
        if f.name not in raw:
            continue
        val = raw[f.name]
        if val is None:
            if f.name not in ("db_port", "api_bind_port", "realtime_bind_port"):
                kwargs[f.name] = None
            continue
        elif f.name in ("db_port", "api_bind_port", "realtime_bind_port"):
            kwargs[f.name] = int(val)
        elif f.name in ("latitude", "longitude", "altitude_meters"):
            kwargs[f.name] = float(val) if val is not None else None
        elif f.name == "column_mapping":
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): (str(v) if v is not None else None) for k, v in val.items()}
        elif f.name == "providers":
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): str(v) for k, v in val.items()}
        elif f.name == "api_keys":
            kwargs[f.name] = val  # already processed above
        else:
            kwargs[f.name] = val
    return WizardState(**kwargs)

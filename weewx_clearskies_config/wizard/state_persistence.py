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
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            result[key.strip()] = value
    except OSError:
        pass
    return result


def save_progress(session_id: str, state: WizardState, config_dir: Path) -> None:
    """Serialize WizardState to a JSON progress file. Atomic write.

    The progress file is written with mode 0600 so only the service user
    can read it.  Secrets (db_password, api_keys, mqtt_password, proxy_secret)
    are stored as-is to allow session recovery without re-entry.
    """
    raw = dataclasses.asdict(state)

    # api_session_id grants access to all setup API endpoints — never persist it.
    raw["api_session_id"] = None

    raw["_saved_at"] = time.time()

    config_dir.mkdir(parents=True, exist_ok=True)
    dest = _progress_path(session_id, config_dir)
    tmp = dest.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        os.replace(tmp, dest)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
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

    if raw.get("mqtt_password") == _SECRET_SENTINEL:
        raw["mqtt_password"] = secrets.get("WEEWX_CLEARSKIES_MQTT_PASSWORD", "")

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


def load_most_recent_progress(config_dir: Path) -> WizardState | None:
    """Load the most recently saved wizard progress file, regardless of session_id.

    Used when a new session starts with blank state but a progress file from a
    previous session exists on disk (e.g. after a service restart or browser
    close).  The file is identified by its ``_saved_at`` timestamp; the
    session_id embedded in the filename is ignored.

    Returns the deserialized WizardState on success, or None if no suitable
    progress file is found.
    """
    best_path: Path | None = None
    best_saved_at: float = -1.0

    try:
        candidates = list(config_dir.glob("wizard_progress_*.json"))
    except OSError as exc:
        logger.warning("Could not scan config_dir for progress files: %s", exc)
        return None

    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            saved_at = raw.get("_saved_at", 0)
            if isinstance(saved_at, (int, float)) and saved_at > best_saved_at:
                best_saved_at = float(saved_at)
                best_path = path
        except (OSError, json.JSONDecodeError):
            pass

    if best_path is None:
        return None

    try:
        raw = json.loads(best_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Corrupt wizard progress file %s: %s", best_path.name, exc)
        return None

    if not isinstance(raw, dict):
        return None

    raw.pop("_saved_at", None)

    secrets = _read_secrets_env(config_dir)

    if raw.get("db_password") == _SECRET_SENTINEL:
        raw["db_password"] = secrets.get("WEEWX_CLEARSKIES_DB_PASSWORD")

    if raw.get("proxy_secret") == _SECRET_SENTINEL:
        raw["proxy_secret"] = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")

    if raw.get("mqtt_password") == _SECRET_SENTINEL:
        raw["mqtt_password"] = secrets.get("WEEWX_CLEARSKIES_MQTT_PASSWORD", "")

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

    # api_session_id is never persisted — always starts blank in a new session.
    raw.pop("api_session_id", None)

    try:
        return _state_from_dict(raw)
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning("Could not reconstruct WizardState from %s: %s", best_path.name, exc)
        return None


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
            # api.conf stores mappings as canonical = db_col (e.g. outTemp = outside_temperature).
            # WizardState.column_mapping expects the inverse: {db_col: canonical}.
            excluded_str = str(mapping_section.get("_excluded", ""))
            excluded = [c.strip() for c in excluded_str.split(",") if c.strip()]
            state.column_mapping = {
                str(v): str(k)
                for k, v in mapping_section.items()
                if v and k != "_excluded"
            }
            for col in excluded:
                state.column_mapping[col] = None

        # [column_units] in api.conf stores db_col = unit (e.g. outTemp = degree_F).
        # Written by the API on apply (T2.6); read here on re-run to pre-populate.
        units_section = api_cfg.get("column_units", {})
        if isinstance(units_section, dict):
            state.column_units = {
                str(k): str(v) for k, v in units_section.items() if v
            }

        providers: dict[str, str] = {}
        for domain in _PROVIDER_DOMAINS:
            domain_section = api_cfg.get(domain, {})
            if isinstance(domain_section, dict):
                provider_id = str(domain_section.get("provider", "")).strip()
                if provider_id:
                    providers[domain] = provider_id
        state.providers = providers

        station_section = api_cfg.get("station", {})
        if isinstance(station_section, dict):
            locale_val = str(station_section.get("default_locale", "")).strip()
            if locale_val:
                state.default_locale = locale_val

        server_section = api_cfg.get("server", {})
        if isinstance(server_section, dict):
            if server_section.get("bind_host"):
                state.api_bind_host = str(server_section["bind_host"])
            if server_section.get("bind_port"):
                try:
                    state.api_bind_port = int(server_section["bind_port"])
                except (ValueError, TypeError):
                    pass

        api_branding_section = api_cfg.get("branding", {})
        if isinstance(api_branding_section, dict):
            if api_branding_section.get("copyright_entity"):
                state.copyright_entity = str(api_branding_section["copyright_entity"])

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

        webcam_section = stack_cfg.get("webcam", {})
        if isinstance(webcam_section, dict):
            enabled_val = str(webcam_section.get("enabled", "false")).lower()
            state.webcam_enabled = enabled_val in ("true", "1", "yes")
            if webcam_section.get("image_url"):
                state.webcam_image_url = str(webcam_section["image_url"])
            if webcam_section.get("video_url"):
                state.webcam_video_url = str(webcam_section["video_url"])
            if webcam_section.get("refresh_interval"):
                try:
                    state.webcam_refresh_interval = int(webcam_section["refresh_interval"])
                except (ValueError, TypeError):
                    pass

        branding_section = stack_cfg.get("branding", {})
        if isinstance(branding_section, dict):
            if branding_section.get("site_title"):
                state.site_title = str(branding_section["site_title"])
            if branding_section.get("copyright_entity"):
                state.copyright_entity = str(branding_section["copyright_entity"])
            if branding_section.get("logo_light_url"):
                state.logo_light_url = str(branding_section["logo_light_url"])
            if branding_section.get("logo_dark_url"):
                state.logo_dark_url = str(branding_section["logo_dark_url"])
            if branding_section.get("logo_alt"):
                state.logo_alt = str(branding_section["logo_alt"])
            if branding_section.get("favicon_url"):
                state.favicon_url = str(branding_section["favicon_url"])
            if branding_section.get("accent"):
                state.accent = str(branding_section["accent"])
            if branding_section.get("default_theme_mode"):
                state.default_theme_mode = str(branding_section["default_theme_mode"])
            if branding_section.get("custom_css_url"):
                state.custom_css_url = str(branding_section["custom_css_url"])

        social_section = stack_cfg.get("social", {})
        if isinstance(social_section, dict):
            if social_section.get("facebook"):
                state.facebook_url = str(social_section["facebook"])
            if social_section.get("twitter"):
                state.twitter_url = str(social_section["twitter"])
            if social_section.get("instagram"):
                state.instagram_url = str(social_section["instagram"])
            if social_section.get("youtube"):
                state.youtube_url = str(social_section["youtube"])

        analytics_section = stack_cfg.get("analytics", {})
        if isinstance(analytics_section, dict):
            if analytics_section.get("google_analytics_id"):
                state.google_analytics_id = str(analytics_section["google_analytics_id"])

        privacy_section = stack_cfg.get("privacy", {})
        if isinstance(privacy_section, dict):
            if privacy_section.get("regions"):
                state.privacy_regions = str(privacy_section["regions"])

        earthquakes_section = stack_cfg.get("earthquakes", {})
        if isinstance(earthquakes_section, dict):
            if earthquakes_section.get("radius_km"):
                try:
                    state.earthquake_radius_km = float(earthquakes_section["radius_km"])
                except (ValueError, TypeError):
                    pass
            if earthquakes_section.get("min_magnitude"):
                try:
                    state.earthquake_min_magnitude = float(earthquakes_section["min_magnitude"])
                except (ValueError, TypeError):
                    pass
            if earthquakes_section.get("default_days"):
                try:
                    days = int(earthquakes_section["default_days"])
                    if days in (1, 7, 14, 30):
                        state.earthquake_default_days = days
                except (ValueError, TypeError):
                    pass

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

        input_section = realtime_cfg.get("input", {})
        if isinstance(input_section, dict):
            mode = str(input_section.get("mode", "direct")).strip()
            if mode in ("direct", "mqtt"):
                state.input_mode = mode
            mqtt_section = input_section.get("mqtt", {})
            if isinstance(mqtt_section, dict):
                if mqtt_section.get("broker_host"):
                    state.mqtt_broker_host = str(mqtt_section["broker_host"])
                if mqtt_section.get("broker_port"):
                    try:
                        state.mqtt_broker_port = int(mqtt_section["broker_port"])
                    except (ValueError, TypeError):
                        pass
                if mqtt_section.get("topic"):
                    state.mqtt_topic = str(mqtt_section["topic"])
                if mqtt_section.get("client_id"):
                    state.mqtt_client_id = str(mqtt_section["client_id"])
                if mqtt_section.get("username"):
                    state.mqtt_username = str(mqtt_section["username"])
                tls_val = str(mqtt_section.get("tls", "false")).lower()
                state.mqtt_tls = tls_val in ("true", "1", "yes")
                if mqtt_section.get("qos"):
                    try:
                        qos = int(mqtt_section["qos"])
                        if qos in (0, 1, 2):
                            state.mqtt_qos = qos
                    except (ValueError, TypeError):
                        pass
                if mqtt_section.get("keepalive"):
                    try:
                        state.mqtt_keepalive = int(mqtt_section["keepalive"])
                    except (ValueError, TypeError):
                        pass
        # MQTT password comes from secrets.env (stored as env var).
        mqtt_password = secrets.get("WEEWX_CLEARSKIES_MQTT_PASSWORD", "")
        if mqtt_password:
            state.mqtt_password = mqtt_password

    state.proxy_secret = secrets.get("WEEWX_CLEARSKIES_PROXY_SECRET")

    # Pre-populate branding fields from branding.json (ADR-022 amendment).
    # branding.json is the authoritative source; stack.conf [branding] is kept
    # as a backup but branding.json wins when present.
    populate_from_branding_json(state, config_dir)

    if state.providers:
        api_keys: dict[str, dict[str, str]] = {}
        for domain, provider_id in state.providers.items():
            existing_creds = api_keys.get(provider_id, {})
            env_prefix = (
                f"WEEWX_CLEARSKIES_{provider_id.upper()}_"
            )
            for env_key, env_val in secrets.items():
                if env_key.startswith(env_prefix):
                    field_name = env_key[len(env_prefix):].lower()
                    existing_creds[field_name] = env_val
            if existing_creds:
                api_keys[provider_id] = existing_creds
        state.api_keys = api_keys

    return state


def populate_from_branding_json(state: WizardState, config_dir: Path) -> None:
    """Populate branding-related state fields from branding.json if it exists.

    Called during wizard re-run to pre-populate the appearance step with the
    values that were written on the previous run.  Gracefully handles a missing
    file (first run) — no fields are changed in that case.

    Per ADR-022 amendment, branding.json is the authoritative source for all
    branding and social fields.  stack.conf [branding] is kept as a backup/
    reference copy but branding.json values take precedence.
    """
    import json as _json

    branding_path = config_dir / "branding.json"
    if not branding_path.exists():
        return

    try:
        data = _json.loads(branding_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError) as exc:
        logger.warning("Could not read branding.json from %s: %s", config_dir, exc)
        return

    if not isinstance(data, dict):
        logger.warning("branding.json at %s is not a JSON object; skipping", config_dir)
        return

    # Populate scalar fields — always overwrite from branding.json (it is
    # authoritative).  Empty strings in the file mean "not set".
    if data.get("siteTitle"):
        state.site_title = str(data["siteTitle"])
    if data.get("copyrightEntity"):
        state.copyright_entity = str(data["copyrightEntity"])
    if data.get("faviconUrl"):
        state.favicon_url = str(data["faviconUrl"])
    if data.get("accent"):
        state.accent = str(data["accent"])
    if data.get("defaultThemeMode"):
        state.default_theme_mode = str(data["defaultThemeMode"])
    if data.get("customCssUrl"):
        state.custom_css_url = str(data["customCssUrl"])
    if data.get("googleAnalyticsId"):
        state.google_analytics_id = str(data["googleAnalyticsId"])
    if data.get("privacyRegions"):
        state.privacy_regions = str(data["privacyRegions"])

    # Nested logo object
    logo = data.get("logo")
    if isinstance(logo, dict):
        if logo.get("lightUrl"):
            state.logo_light_url = str(logo["lightUrl"])
        if logo.get("darkUrl"):
            state.logo_dark_url = str(logo["darkUrl"])
        if logo.get("alt"):
            state.logo_alt = str(logo["alt"])

    # Nested social object
    social = data.get("social")
    if isinstance(social, dict):
        if social.get("facebook"):
            state.facebook_url = str(social["facebook"])
        if social.get("twitter"):
            state.twitter_url = str(social["twitter"])
        if social.get("instagram"):
            state.instagram_url = str(social["instagram"])
        if social.get("youtube"):
            state.youtube_url = str(social["youtube"])


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
    _INT_FIELDS = {"db_port", "api_bind_port", "realtime_bind_port", "mqtt_broker_port", "mqtt_qos", "mqtt_keepalive", "webcam_refresh_interval", "earthquake_default_days"}
    _FLOAT_FIELDS = {"latitude", "longitude", "altitude_meters", "earthquake_radius_km", "earthquake_min_magnitude"}
    _BOOL_FIELDS = {"mqtt_tls", "schema_skipped", "webcam_enabled"}

    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(WizardState):
        if f.name not in raw:
            continue
        val = raw[f.name]
        if val is None:
            if f.name not in _INT_FIELDS:
                kwargs[f.name] = None
            continue
        elif f.name in _INT_FIELDS:
            kwargs[f.name] = int(val)
        elif f.name in _FLOAT_FIELDS:
            kwargs[f.name] = float(val) if val is not None else None
        elif f.name in _BOOL_FIELDS:
            if isinstance(val, bool):
                kwargs[f.name] = val
            else:
                kwargs[f.name] = str(val).lower() in ("true", "1", "yes")
        elif f.name == "column_mapping":
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): (str(v) if v is not None else None) for k, v in val.items()}
        elif f.name == "column_units":
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): str(v) for k, v in val.items() if v}
        elif f.name == "providers":
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): str(v) for k, v in val.items()}
        elif f.name == "api_keys":
            kwargs[f.name] = val  # already processed above
        elif f.name == "imported_config":
            # Stored as a dict or None; accept as-is.
            kwargs[f.name] = val if isinstance(val, dict) else None
        elif f.name == "units":
            # Stored as a dict of {group: unit} or None.
            if isinstance(val, dict):
                kwargs[f.name] = {str(k): str(v) for k, v in val.items()}
            else:
                kwargs[f.name] = None
        else:
            kwargs[f.name] = val
    return WizardState(**kwargs)

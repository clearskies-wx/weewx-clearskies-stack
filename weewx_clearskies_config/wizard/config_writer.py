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

import json
import os
import shutil
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

    # Ensure ConfigObj writes UTF-8 bytes so non-ASCII values (e.g. unit
    # labels containing "°") are preserved correctly.
    cfg.encoding = "utf-8"
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

    Not yet implemented (BUG A7).  The API writes its own config via
    POST /setup/apply (ADR-038); this function is reserved for a future
    local-cache copy of the API's config if that requirement is confirmed.

    Raises:
        NotImplementedError: Always.  Tests for this function are marked
            xfail pending BUG A7 resolution.
    """
    raise NotImplementedError("write_api_conf is not implemented (BUG A7)")


def write_stack_conf(state: WizardState, config_dir: Path) -> Path:
    """Write stack.conf from *state*.

    Sections written:
      [ui]     — station display settings
      [webcam] — webcam config for wizard re-run pre-fill

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
        "altitude_unit": state.altitude_unit,
        "timezone": state.timezone or "",
        "topology": state.topology,
        "eula_accepted_at": state.eula_accepted_at,
    }

    cfg["webcam"] = {
        "enabled": str(state.webcam_enabled).lower(),
        "image_url": state.webcam_image_url,
        "video_url": state.webcam_video_url,
        "refresh_interval": str(state.webcam_refresh_interval),
    }

    cfg["branding"] = {
        "site_title": state.site_title,
        "logo_light_url": state.logo_light_url,
        "logo_dark_url": state.logo_dark_url,
        "logo_alt": state.logo_alt,
        "favicon_url": state.favicon_url,
        "accent": state.accent,
        "default_theme_mode": state.default_theme_mode,
        "custom_css_url": state.custom_css_url,
    }

    cfg["social"] = {
        "facebook": state.facebook_url,
        "twitter": state.twitter_url,
        "instagram": state.instagram_url,
        "youtube": state.youtube_url,
    }

    # Phase 4 fields — saved locally so wizard re-run can pre-populate them.
    # The API does not yet accept these fields; they are sent only after the API update.
    cfg["analytics"] = {
        "google_analytics_id": state.google_analytics_id,
    }

    cfg["privacy"] = {
        "regions": state.privacy_regions,
    }

    cfg["earthquakes"] = {
        "radius_km": str(state.earthquake_radius_km),
        "min_magnitude": str(state.earthquake_min_magnitude),
        "default_days": str(state.earthquake_default_days),
    }

    # TLS configuration (step 14) — API token is never written here;
    # it is stored in secrets.env (mode 0600) only.
    tls_section: dict[str, str] = {"mode": state.tls_mode}
    if state.tls_mode in ("acme_http01", "acme_dns01"):
        tls_section["domain"] = state.tls_domain
        tls_section["acme_email"] = state.tls_acme_email
    if state.tls_mode == "acme_dns01":
        tls_section["dns_provider"] = state.tls_dns_provider
        # dns_api_token intentionally omitted — lives in secrets.env only.
    cfg["tls"] = tls_section

    content = _wrap_with_managed_region(cfg)
    dest = config_dir / "stack.conf"
    if dest.exists():
        shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
    _write_file(dest, content)
    return dest


def write_branding_json(state: WizardState, config_dir: Path) -> Path:
    """Write branding.json for Caddy to serve to the dashboard.

    Per ADR-022 amendment: branding config is no longer sent to the API.
    The wizard writes branding.json directly to config_dir (typically
    /etc/weewx-clearskies/) and Caddy serves it as a static file at
    /branding.json, matching the same pattern as webcam.json.

    Returns the path to the written file.
    """
    branding = {
        "siteTitle": state.site_title or "",
        "copyrightEntity": state.copyright_entity or "",
        "logo": {
            "lightUrl": state.logo_light_url or "",
            "darkUrl": state.logo_dark_url or "",
            "alt": state.logo_alt or "",
        },
        "faviconUrl": state.favicon_url or "",
        "accent": state.accent or "blue",
        "defaultThemeMode": state.default_theme_mode or "auto-os",
        "customCssUrl": state.custom_css_url or None,
        "social": {
            "facebook": state.facebook_url or "",
            "twitter": state.twitter_url or "",
            "instagram": state.instagram_url or "",
            "youtube": state.youtube_url or "",
        },
        "googleAnalyticsId": state.google_analytics_id or "",
        "privacyRegions": state.privacy_regions or "global",
    }
    dest = config_dir / "branding.json"
    if dest.exists():
        shutil.copy2(dest, dest.with_suffix(".json.bak"))
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(branding, f, indent=2, ensure_ascii=False)
        f.write("\n")
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

    Writes only secrets consumed by local services (stack).
    Database passwords and provider API keys are sent to the API via
    POST /setup/apply and are managed in the API's own secrets.env.

    Local secrets written:
      - WEEWX_CLEARSKIES_PROXY_SECRET (shared with API for HMAC validation;
        also written by the API — both sides need the same value)

    Not written here:
      - WEEWX_CLEARSKIES_DB_PASSWORD (managed by the API)
      - Provider API keys (managed by the API)
      - WEEWX_CLEARSKIES_BOOTSTRAP_TOKEN (one-time token; already consumed)

    The file is written with mode 0600 (owner read/write only).
    Returns the path to the written file.
    """
    dest = config_dir / "secrets.env"

    # Read-merge: preserve keys we don't manage (admin credentials written
    # by the bootstrap flow) instead of overwriting the entire file.
    from .state_persistence import _read_secrets_env

    existing = _read_secrets_env(config_dir)

    if state.proxy_secret:
        existing["WEEWX_CLEARSKIES_PROXY_SECRET"] = state.proxy_secret
    elif "WEEWX_CLEARSKIES_PROXY_SECRET" in existing:
        del existing["WEEWX_CLEARSKIES_PROXY_SECRET"]

    # TLS DNS API token — only written for DNS-01 mode; cleared otherwise so
    # stale tokens are not left behind if the operator switches to a different mode.
    if state.tls_mode == "acme_dns01" and state.tls_dns_api_token:
        existing["WEEWX_CLEARSKIES_TLS_DNS_API_TOKEN"] = state.tls_dns_api_token
    elif "WEEWX_CLEARSKIES_TLS_DNS_API_TOKEN" in existing:
        del existing["WEEWX_CLEARSKIES_TLS_DNS_API_TOKEN"]

    lines = [
        "# weewx-clearskies secrets — do not commit this file to version control.\n",
        "# Generated by the setup wizard. Managed by weewx-clearskies-config.\n",
        "# Database password and provider API keys are stored in the API's secrets.env.\n",
        "\n",
    ]
    for key, value in existing.items():
        lines.append(f"{key}={_shell_quote_value(value)}\n")

    content = "".join(lines)
    if dest.exists():
        shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
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
            "the dashboard host so the HMAC validation succeeds:\n",
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
        f"scp {config_dir}/stack.conf user@server:/etc/weewx-clearskies/\n",
        f"scp {config_dir}/secrets.env user@server:/etc/weewx-clearskies/\n",
        "```\n",
        "\n",
        "Ensure `secrets.env` is chmod 0600 on the target server.\n",
        "Restart the API on the weewx host to load the configuration it received during setup.\n",
    ]

    dest = config_dir / "bootstrap-summary.md"
    _write_file(dest, "".join(lines))
    return dest


def build_skin_conf_payload(state: WizardState) -> dict[str, Any]:
    """Build skin_conf payload for POST /setup/apply (ADR-043).

    Always includes unit group selections (from state.units, or falling back
    to the US preset when the unit step was not completed).  Includes
    additional [Units] subsections (string_formats, labels, ordinates,
    time_formats, degree_days, trend) plus top-level labels, extras, and
    almanac if the operator imported an existing skin.conf.

    The returned dict is added to the api_payload as "skin_conf" before
    calling client.apply().

    Args:
        state: The current WizardState, potentially populated by a prior
               skin.conf import (state.imported_config) and/or a completed
               unit step (state.units).

    Returns:
        Dict suitable for the "skin_conf" key in the POST /setup/apply
        payload.
    """
    from weewx_clearskies_config.wizard.units import UNIT_PRESETS

    payload: dict[str, Any] = {}

    # [Units] section — groups always present; other subsections from import.
    units: dict[str, Any] = {}
    if state.units is not None:
        units["groups"] = dict(state.units)
    else:
        units["groups"] = dict(UNIT_PRESETS["us"])

    # Carry forward imported [Units] subsections when an import was done.
    if state.imported_config is not None:
        imp_units = state.imported_config.get("units", {})
        for key in (
            "string_formats",
            "labels",
            "ordinates",
            "time_formats",
            "degree_days",
            "trend",
        ):
            value = imp_units.get(key)
            if value:
                units[key] = value

    payload["units"] = units

    # [Labels][[Generic]], [Extras], [Almanac] — from import only.
    if state.imported_config is not None:
        raw_labels = state.imported_config.get("labels", {})
        if raw_labels:
            # skin_import.py returns labels as a flat dict from [Labels][[Generic]].
            # Wrap under the "generic" key to mirror the skin.conf section hierarchy.
            payload["labels"] = {"generic": raw_labels}

        extras = state.imported_config.get("extras", {})
        if extras:
            payload["extras"] = extras

        almanac = state.imported_config.get("almanac", {})
        if almanac:
            payload["almanac"] = almanac

    return payload


def apply_wizard(state: WizardState, config_dir: Path) -> dict[str, Any]:
    """Write local config files and secrets.env from *state*.

    api.conf is written by the API itself when the wizard sends the apply
    payload via POST /setup/apply (ADR-038).  This function writes only the
    locally-consumed config files: stack.conf, branding.json, and secrets.env.

    Orchestrates calls to write_stack_conf and write_secrets_env.
    Returns a summary dict:
      {
        "files_written": [<path>, ...],
        "secrets_written": [<path>, ...],
        "summary_path": "<path>",
      }
    """
    files_written = []
    secrets_written = []

    files_written.append(str(write_stack_conf(state, config_dir)))
    files_written.append(str(write_branding_json(state, config_dir)))
    secrets_written.append(str(write_secrets_env(state, config_dir)))

    result: dict[str, Any] = {
        "files_written": files_written,
        "secrets_written": secrets_written,
    }

    summary_path = write_bootstrap_summary(state, result, config_dir)
    result["summary_path"] = str(summary_path)

    return result

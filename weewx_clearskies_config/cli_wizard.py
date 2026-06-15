"""Interactive terminal wizard and headless mode for Clear Skies configuration.

cli_wizard.py implements two configuration paths that reuse the same wizard
backend modules as the web UI:

  run_cli_wizard(config_dir)  — interactive step-by-step prompts via click
  run_headless(config_dir, **kwargs) — non-interactive flag-driven path

Both paths populate a WizardState and call apply_wizard() to write config files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _step_header(step: int, title: str) -> None:
    click.echo("")
    click.echo(f"  Step {step}: {title}")
    click.echo("  " + "-" * (len(title) + 8))


def _ok(msg: str) -> None:
    click.echo(f"  [OK] {msg}")


def _warn(msg: str) -> None:
    click.echo(f"  [WARN] {msg}")


def _err(msg: str) -> None:
    click.echo(f"  [ERROR] {msg}", err=True)


# ---------------------------------------------------------------------------
# Individual wizard steps
# ---------------------------------------------------------------------------


def _step_db(state: Any) -> None:
    """Step 1: DB connection parameters and connectivity test."""
    from weewx_clearskies_config.wizard.db import test_connection

    _step_header(1, "Database Connection")

    # Try to auto-detect from weewx.conf first.
    weewx_conf_path = "/etc/weewx/weewx.conf"
    autodetected = False
    try:
        from weewx_clearskies_config.wizard.db import detect_from_weewx_conf

        detected = detect_from_weewx_conf(weewx_conf_path)
        click.echo(f"  Auto-detected settings from {weewx_conf_path}.")
        default_host = detected["host"]
        default_port = detected["port"]
        default_user = detected["user"]
        default_db = detected["db_name"]
        autodetected = True
    except (FileNotFoundError, KeyError, ValueError):
        default_host = "localhost"
        default_port = 3306
        default_user = "weewx"
        default_db = "weewx"

    if autodetected:
        click.echo(
            f"  Detected: host={default_host} port={default_port}"
            f" user={default_user} db={default_db}"
        )

    state.db_host = click.prompt("  Database host", default=default_host)
    state.db_port = click.prompt("  Database port", default=default_port, type=int)
    state.db_user = click.prompt("  Database user", default=default_user)
    state.db_password = click.prompt(
        "  Database password", hide_input=True, default=""
    )
    state.db_name = click.prompt("  Database name", default=default_db)

    click.echo("  Testing connection...")
    result = test_connection(
        state.db_host, state.db_port, state.db_user, state.db_password, state.db_name
    )
    if result["success"]:
        _ok(f"Connected. Server: {result['server_version']}")
    else:
        _err(f"Connection failed: {result['error']}")
        if not click.confirm("  Continue anyway?", default=False):
            raise SystemExit(1)


def _step_schema(state: Any) -> None:
    """Step 2: Schema introspection and column mapping for non-stock columns."""
    from weewx_clearskies_config.wizard.db import build_db_url
    from weewx_clearskies_config.wizard.schema import introspect_schema

    _step_header(2, "Schema Introspection")
    click.echo("  Inspecting archive table columns...")

    db_url = build_db_url(
        state.db_host,
        state.db_port,
        state.db_user,
        state.db_password,
        state.db_name,
    )

    try:
        schema = introspect_schema(db_url)
    except Exception as exc:  # noqa: BLE001
        _warn(f"Schema introspection failed: {exc}. Skipping column mapping.")
        return

    total = schema["total_columns"]
    stock = schema["stock_mapped"]
    unmapped = schema.get("unmapped_columns", [])

    _ok(
        f"Found {total} column(s): {stock} auto-mapped (stock weewx),"
        f" {len(unmapped)} need review."
    )

    if not unmapped:
        click.echo("  No unmapped columns — nothing to do.")
        return

    click.echo(
        "  For each non-stock column, enter a canonical name or press Enter to skip."
    )
    for col in unmapped:
        db_name = col["db_name"]
        suggested = col.get("suggested")
        confidence = col.get("confidence", "none")

        if suggested and confidence in ("high", "medium"):
            prompt_text = f"  Map '{db_name}' to"
            mapping = click.prompt(prompt_text, default=suggested)
        else:
            hint = f" (suggested: {suggested})" if suggested else ""
            mapping = click.prompt(
                f"  Map '{db_name}' to{hint} (or 'skip')", default="skip"
            )

        if mapping and mapping.lower() != "skip":
            state.column_mapping[db_name] = mapping
        else:
            state.column_mapping[db_name] = None


def _step_station(state: Any) -> None:
    """Step 3: Station identity — try weewx.conf auto-detect, then prompt."""
    _step_header(3, "Station Identity")

    # Try to load defaults from weewx.conf.
    weewx_conf_path = "/etc/weewx/weewx.conf"
    default_name = ""
    default_lat: float | None = None
    default_lon: float | None = None
    default_alt: float | None = None

    try:
        from weewx_clearskies_config.wizard.station import station_from_weewx_conf

        info = station_from_weewx_conf(weewx_conf_path)
        default_name = info.get("station_name") or info.get("location") or ""
        default_lat = info.get("latitude")
        default_lon = info.get("longitude")
        default_alt = info.get("altitude_meters")
        if any(v is not None for v in (default_lat, default_lon, default_alt)):
            click.echo(f"  Auto-detected station info from {weewx_conf_path}.")
    except (FileNotFoundError, KeyError):
        pass

    state.station_name = click.prompt(
        "  Station name", default=default_name or "My Weather Station"
    )

    lat_default = default_lat if default_lat is not None else 0.0
    lon_default = default_lon if default_lon is not None else 0.0
    alt_default = default_alt if default_alt is not None else 0.0

    state.latitude = click.prompt(
        "  Latitude (decimal degrees)", default=lat_default, type=float
    )
    state.longitude = click.prompt(
        "  Longitude (decimal degrees)", default=lon_default, type=float
    )
    state.altitude_meters = click.prompt(
        "  Altitude (meters)", default=alt_default, type=float
    )

    # Try to auto-detect timezone from coordinates.
    tz_default = "UTC"
    if state.latitude is not None and state.longitude is not None:
        try:
            from weewx_clearskies_config.wizard.station import lookup_timezone

            detected_tz = lookup_timezone(state.latitude, state.longitude)
            if detected_tz:
                tz_default = detected_tz
                click.echo(f"  Auto-detected timezone: {tz_default}")
        except Exception:  # noqa: BLE001
            pass

    state.timezone = click.prompt("  Timezone (IANA)", default=tz_default)


def _step_providers(state: Any) -> None:
    """Step 4: Provider selection per domain."""
    from weewx_clearskies_config.wizard.providers import (
        providers_by_domain,
        recommend_providers,
    )

    _step_header(4, "Provider Selection")

    # Build recommendations if we have coordinates.
    recommendations: dict[str, str] = {}
    if state.latitude is not None and state.longitude is not None:
        try:
            recommendations = recommend_providers(state.latitude, state.longitude)
        except Exception:  # noqa: BLE001
            pass

    domain_labels = {
        "forecast": "Forecast",
        "alerts": "Weather Alerts",
        "aqi": "Air Quality (AQI)",
        "earthquakes": "Earthquakes",
        "radar": "Radar",
    }

    grouped = providers_by_domain()

    for domain in ("forecast", "alerts", "aqi", "earthquakes", "radar"):
        providers = grouped.get(domain, [])
        if not providers:
            continue

        label = domain_labels.get(domain, domain)
        click.echo(f"\n  {label} providers:")
        for i, p in enumerate(providers, 1):
            rec_marker = " (recommended)" if recommendations.get(domain) == p.provider_id else ""
            auth_note = " [requires API key]" if p.auth_fields else " [keyless]"
            click.echo(
                f"    {i}. {p.display_name} ({p.geographic_coverage})"
                f"{auth_note}{rec_marker}"
            )

        # Default to the recommended provider index, or 1 if no recommendation.
        rec_id = recommendations.get(domain)
        default_idx = 1
        if rec_id:
            for idx, p in enumerate(providers, 1):
                if p.provider_id == rec_id:
                    default_idx = idx
                    break

        while True:
            choice = click.prompt(
                f"  Select {label} provider (1-{len(providers)})",
                default=default_idx,
                type=int,
            )
            if 1 <= choice <= len(providers):
                selected = providers[choice - 1]
                state.providers[domain] = selected.provider_id
                _ok(f"{label}: {selected.display_name}")
                break
            _err(f"Invalid choice; enter a number between 1 and {len(providers)}.")


def _step_api_keys(state: Any) -> None:
    """Step 5: Collect API credentials for selected providers that need them."""
    from weewx_clearskies_config.wizard.providers import get_provider, test_provider

    _step_header(5, "API Keys")

    has_keyed_providers = False
    for domain, provider_id in state.providers.items():
        provider = get_provider(provider_id)
        if provider is None or not provider.auth_fields:
            continue

        has_keyed_providers = True
        click.echo(f"\n  {provider.display_name} requires credential(s):")
        creds: dict[str, str] = {}
        for field_name in provider.auth_fields:
            value = click.prompt(
                f"    {field_name}", hide_input=True, default="", show_default=False
            )
            if value:
                creds[field_name] = value

        state.api_keys[provider_id] = creds

        # Offer connectivity test if all fields provided.
        if len(creds) == len(provider.auth_fields) and creds:
            if click.confirm(f"  Test connectivity to {provider.display_name}?", default=True):
                click.echo("  Testing...")
                result = test_provider(provider, creds)
                if result["success"]:
                    _ok(f"Connected in {result.get('response_time_ms', '?')}ms.")
                else:
                    _warn(
                        f"Test failed: {result.get('error', 'unknown error')}"
                        + (
                            f" (HTTP {result['status_code']})"
                            if "status_code" in result
                            else ""
                        )
                    )

    if not has_keyed_providers:
        click.echo("  All selected providers are keyless — no credentials needed.")


def _step_topology(state: Any) -> None:
    """Step 6: Deployment topology."""
    from weewx_clearskies_config.wizard.topology import (
        generate_proxy_secret,
        topology_defaults,
    )

    _step_header(6, "Deployment Topology")
    click.echo("  same-host: API, realtime, and dashboard all on one machine.")
    click.echo("  cross-host: dashboard on a separate host (requires shared secret).")

    topology_choice = click.prompt(
        "  Topology",
        type=click.Choice(["same-host", "cross-host"]),
        default="same-host",
    )
    state.topology = topology_choice

    defaults = topology_defaults(topology_choice == "same-host")
    state.api_bind_host = defaults["api_bind_host"]
    state.api_bind_port = defaults["api_bind_port"]

    if defaults["needs_proxy_secret"]:
        secret = generate_proxy_secret()
        state.proxy_secret = secret
        _ok("Generated proxy shared secret (stored in secrets.env).")
    else:
        state.proxy_secret = None


def _step_bind_addresses(state: Any) -> None:
    """Step 7: Bind address overrides."""
    _step_header(7, "Bind Addresses")
    click.echo(
        f"  Defaults based on topology ({state.topology}):\n"
        f"    API:      {state.api_bind_host}:{state.api_bind_port}"
    )

    if click.confirm("  Override bind addresses?", default=False):
        state.api_bind_host = click.prompt(
            "    API bind host", default=state.api_bind_host
        )
        state.api_bind_port = click.prompt(
            "    API bind port", default=state.api_bind_port, type=int
        )
    else:
        _ok("Using defaults.")


def _step_review_apply(state: Any, config_dir: Path) -> None:
    """Step 8: Summary review and config file generation."""
    from weewx_clearskies_config.wizard.config_writer import apply_wizard

    _step_header(8, "Review and Apply")

    # Show a summary.
    click.echo("  Configuration summary:")
    click.echo(f"    Database: {state.db_user}@{state.db_host}:{state.db_port}/{state.db_name}")
    click.echo(f"    Station:  {state.station_name} ({state.latitude}, {state.longitude})")
    click.echo(f"    Timezone: {state.timezone}")
    click.echo(f"    Topology: {state.topology}")
    click.echo(f"    API bind: {state.api_bind_host}:{state.api_bind_port}")
    if state.providers:
        click.echo("    Providers:")
        for domain, pid in state.providers.items():
            click.echo(f"      {domain}: {pid}")
    mapped = {k: v for k, v in state.column_mapping.items() if v}
    if mapped:
        click.echo(f"    Custom column mappings: {len(mapped)}")

    click.echo("")
    if not click.confirm("  Apply and write configuration files?", default=True):
        click.echo("  Aborted. No files written.")
        return

    click.echo(f"  Writing configuration to {config_dir} ...")
    try:
        result = apply_wizard(state, config_dir)
    except Exception as exc:  # noqa: BLE001
        _err(f"Failed to write configuration: {exc}")
        raise SystemExit(1) from exc

    for path in result.get("files_written", []):
        _ok(f"Written: {path}")
    for path in result.get("secrets_written", []):
        _ok(f"Written (secrets): {path}")

    click.echo("")
    click.echo("  Configuration complete.")
    click.echo(
        "  Start the Clear Skies API with: weewx-clearskies-api"
        " (or via your systemd/docker setup)."
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_cli_wizard(config_dir: Path) -> None:
    """Interactive terminal wizard — mirrors web wizard steps 1-8."""
    from weewx_clearskies_config.wizard.state import WizardState

    click.echo("")
    click.echo("  Clear Skies -- Configuration Wizard (CLI)")
    click.echo("  ==========================================")

    state = WizardState()

    _step_db(state)
    _step_schema(state)
    _step_station(state)
    _step_providers(state)
    _step_api_keys(state)
    _step_topology(state)
    _step_bind_addresses(state)
    _step_review_apply(state, config_dir)


def run_headless(
    config_dir: Path,
    db_host: str | None,
    db_port: int | None,
    db_user: str | None,
    db_password: str | None,
    db_name: str | None,
    forecast_provider: str | None,
    topology: str | None,
) -> None:
    """Non-interactive headless configuration using CLI flag values.

    Applies defaults for any flags not provided.  Writes configuration files
    directly without user prompts.  Exits with code 1 on any error.
    """
    from weewx_clearskies_config.wizard.config_writer import apply_wizard
    from weewx_clearskies_config.wizard.state import WizardState
    from weewx_clearskies_config.wizard.topology import (
        generate_proxy_secret,
        topology_defaults,
    )

    state = WizardState(
        db_host=db_host or "localhost",
        db_port=db_port if db_port is not None else 3306,
        db_user=db_user or "weewx",
        db_password=db_password or "",
        db_name=db_name or "weewx",
    )

    # Provider defaults.
    resolved_topology = topology or "same-host"
    state.topology = resolved_topology

    if forecast_provider:
        state.providers["forecast"] = forecast_provider

    # Apply topology defaults for bind addresses.
    defaults = topology_defaults(resolved_topology == "same-host")
    state.api_bind_host = defaults["api_bind_host"]
    state.api_bind_port = defaults["api_bind_port"]

    if defaults["needs_proxy_secret"]:
        state.proxy_secret = generate_proxy_secret()

    click.echo(
        f"Headless mode: writing configuration to {config_dir} ..."
    )
    try:
        result = apply_wizard(state, config_dir)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    for path in result.get("files_written", []):
        click.echo(f"  Written: {path}")
    for path in result.get("secrets_written", []):
        click.echo(f"  Written (secrets): {path}")
    click.echo("Done.")

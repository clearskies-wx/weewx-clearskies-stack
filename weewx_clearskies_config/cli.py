from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path

import click

from weewx_clearskies_config.auth import (
    BootstrapManager,
    _config_dir,
    read_secrets,
    write_secrets,
)


def _resolve_addresses(addr: str, port: int) -> list[str]:
    results = socket.getaddrinfo(addr, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        host = sockaddr[0]
        if host not in seen:
            seen.append(host)
    return seen


def _is_private_address(addr: str) -> bool:
    addr = addr.strip("[]")
    try:
        ip = ipaddress.ip_address(addr)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return True


def _scheme(tls: bool) -> str:
    return "https" if tls else "http"


def _format_url(scheme: str, host: str, port: int) -> str:
    try:
        ip = ipaddress.ip_address(host)
        if isinstance(ip, ipaddress.IPv6Address):
            return f"{scheme}://[{host}]:{port}/"
        return f"{scheme}://{host}:{port}/"
    except ValueError:
        return f"{scheme}://{host}:{port}/"


def _print_banner(
    bind_addresses: list[str],
    port: int,
    tls: bool,
    bootstrap_token: str | None,
    fingerprint: str | None,
    *,
    localhost_requested: bool = False,
) -> None:
    scheme = _scheme(tls)
    click.echo("")
    click.echo("  Clear Skies — Configuration UI")
    click.echo("  --------------------------------")
    non_private = False
    for addr in bind_addresses:
        url = _format_url(scheme, addr, port)
        click.echo(f"  Listening: {url}")
        if not _is_private_address(addr):
            non_private = True

    # Uvicorn only binds one host at a time.  When --localhost is requested we
    # bind 127.0.0.1 only; ::1 is not bound.
    if localhost_requested and "127.0.0.1" in bind_addresses and "::1" not in bind_addresses:
        click.echo(
            "  Note: IPv6 loopback (::1) is not bound — uvicorn limitation. "
            "Use --bind ::1 for IPv6-only."
        )

    if non_private:
        click.echo("")
        click.echo(
            "  Note: Bound to a non-private address. "
            "Ensure your firewall settings are appropriate."
        )

    if tls and fingerprint:
        click.echo(f"  TLS fingerprint (SHA-256): {fingerprint}")

    if bootstrap_token:
        first_addr = bind_addresses[0] if bind_addresses else "localhost"
        if first_addr in ("::", "0.0.0.0"):
            first_addr = "localhost"
        url = _format_url(scheme, first_addr, port)
        click.echo("")
        click.echo("  First-time setup: open this URL to set your admin password:")
        click.echo(f"    {url}bootstrap?token={bootstrap_token}")

    click.echo("")


@click.command()
@click.option("--localhost", "bind_localhost", is_flag=True, default=False)
@click.option("--bind", "bind_addr", default=None, metavar="ADDR")
@click.option("--port", default=9876, show_default=True, metavar="PORT")
@click.option("--tls", "tls_enabled", is_flag=True, default=False)
@click.option("--cli", "cli_mode", is_flag=True, default=False)
@click.option("--reset", "reset_config", is_flag=True, default=False)
@click.option("--reset-admin-password", is_flag=True, default=False)
@click.option("--show-secrets", is_flag=True, default=False)
@click.option("--headless", is_flag=True, default=False)
@click.option("--db-host", default=None, help="Headless: database host")
@click.option("--db-port", default=None, type=int, help="Headless: database port")
@click.option("--db-user", default=None, help="Headless: database user")
@click.option("--db-password", default=None, help="Headless: database password")
@click.option("--db-name", default=None, help="Headless: database name")
@click.option("--forecast-provider", default=None, help="Headless: forecast provider id")
@click.option(
    "--topology",
    "headless_topology",
    default=None,
    type=click.Choice(["same-host", "cross-host"]),
    help="Headless: deployment topology",
)
def cli(
    bind_localhost: bool,
    bind_addr: str | None,
    port: int,
    tls_enabled: bool,
    cli_mode: bool,
    reset_config: bool,
    reset_admin_password: bool,
    show_secrets: bool,
    headless: bool,
    db_host: str | None,
    db_port: int | None,
    db_user: str | None,
    db_password: str | None,
    db_name: str | None,
    forecast_provider: str | None,
    headless_topology: str | None,
) -> None:
    if bind_localhost and bind_addr:
        click.echo("Error: --localhost and --bind are mutually exclusive.", err=True)
        sys.exit(1)

    # --- Action-only flags (run and exit, no server) ---

    if cli_mode:
        from weewx_clearskies_config.cli_wizard import run_cli_wizard

        run_cli_wizard(_config_dir())
        sys.exit(0)

    if reset_config:
        click.echo("Config reset not yet implemented.")
        sys.exit(0)

    if headless:
        from weewx_clearskies_config.cli_wizard import run_headless

        run_headless(
            config_dir=_config_dir(),
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            forecast_provider=forecast_provider,
            topology=headless_topology,
        )
        sys.exit(0)

    if show_secrets:
        secrets = read_secrets()
        if not secrets:
            click.echo("No secrets found.")
        else:
            for key, value in secrets.items():
                click.echo(f"{key}={value}")
        sys.exit(0)

    if reset_admin_password:
        secrets = read_secrets()
        secrets.pop("WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH", None)
        secrets.pop("WEEWX_CLEARSKIES_ADMIN_USERNAME", None)
        write_secrets(secrets)
        click.echo("Admin credentials cleared from secrets.env.")
        sys.exit(0)

    # --- Determine bind addresses ---

    if bind_localhost:
        bind_addresses = ["127.0.0.1", "::1"]
    elif bind_addr:
        bind_addresses = _resolve_addresses(bind_addr, port)
        if not bind_addresses:
            click.echo(f"Error: could not resolve bind address: {bind_addr}", err=True)
            sys.exit(1)
    else:
        # Default: dual-stack all interfaces
        bind_addresses = ["::"]

    # --- TLS setup ---

    cert_path: Path | None = None
    key_path: Path | None = None
    fingerprint: str | None = None

    if tls_enabled:
        from weewx_clearskies_config.tls import get_cert_fingerprint, load_or_generate_cert

        config_dir = _config_dir()
        cert_path, key_path = load_or_generate_cert(bind_addresses, config_dir)
        fingerprint = get_cert_fingerprint(cert_path)

    # --- Bootstrap token (only when no admin credentials stored) ---

    stored = read_secrets()
    bootstrap_manager: BootstrapManager | None = None
    bootstrap_token: str | None = None

    if "WEEWX_CLEARSKIES_ADMIN_USERNAME" not in stored:
        bootstrap_manager = BootstrapManager()
        bootstrap_token = bootstrap_manager.generate()

    # --- Print startup banner ---

    _print_banner(
        bind_addresses,
        port,
        tls_enabled,
        bootstrap_token,
        fingerprint,
        localhost_requested=bind_localhost,
    )

    # --- Build and launch the app ---

    from weewx_clearskies_config.app import AppConfig, create_app

    app_config = AppConfig(
        bind_host=bind_addresses[0],
        bind_port=port,
        tls_enabled=tls_enabled,
        tls_cert_path=cert_path,
        tls_key_path=key_path,
        config_dir=_config_dir(),
        bootstrap_manager=bootstrap_manager,
    )
    app = create_app(app_config)

    import uvicorn

    ssl_kwargs: dict[str, object] = {}
    if tls_enabled and cert_path and key_path:
        ssl_kwargs = {
            "ssl_certfile": str(cert_path),
            "ssl_keyfile": str(key_path),
        }

    if bind_localhost:
        # Uvicorn only takes one host; run two sequential servers is not viable
        # in a single process. Bind to both loopback addresses using the first
        # one as the uvicorn host; the user can access via either.
        # A proper dual-bind would require a custom asyncio server setup (A2+).
        # For A1 we bind the IPv4 loopback and note the limitation.
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            **ssl_kwargs,  # type: ignore[arg-type]
        )
    else:
        uvicorn.run(
            app,
            host=bind_addresses[0],
            port=port,
            **ssl_kwargs,  # type: ignore[arg-type]
        )

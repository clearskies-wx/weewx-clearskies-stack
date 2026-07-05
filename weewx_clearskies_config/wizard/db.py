"""DB connection testing and weewx.conf auto-detection.

Uses SQLAlchemy + pymysql for connection tests.  Uses configobj directly
(not the API's load_weewx_conf) to avoid a circular dependency in the wizard
bootstrap path where the API may not yet be installed.

Note: the web wizard (routes.py) no longer calls these functions — it uses
ApiClient.test_db() and ApiClient.get_db_defaults() instead (ADR-038).
These functions have no production caller since the CLI wizard was removed;
they are exercised only by tests. Kept in case a future standalone
(no-API-session) path needs them.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError


def build_db_url(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
) -> str:
    """Return a pymysql SQLAlchemy URL for the given connection parameters.

    Passwords are percent-encoded so special characters don't break the URL.
    """
    encoded_password = urllib.parse.quote(password, safe="")
    encoded_user = urllib.parse.quote(user, safe="")
    return f"mysql+pymysql://{encoded_user}:{encoded_password}@{host}:{port}/{db_name}"


def test_connection(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
) -> dict[str, Any]:
    """Test the DB connection by executing ``SELECT 1``.

    Returns ``{"success": True, "server_version": "..."}`` on success or
    ``{"success": False, "error": "..."}`` on failure.  A 5-second connect
    timeout prevents indefinite hangs in the wizard UI.
    """
    url = build_db_url(host, port, user, password, db_name)
    try:
        engine = create_engine(
            url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=False,
        )
        with engine.connect() as conn:
            row = conn.execute(text("SELECT VERSION()")).fetchone()
            version = str(row[0]) if row else "unknown"
        engine.dispose()
        return {"success": True, "server_version": version}
    except OperationalError as exc:
        return {"success": False, "error": _friendly_db_error(str(exc))}
    except SQLAlchemyError as exc:
        return {"success": False, "error": _friendly_db_error(str(exc))}


def detect_from_weewx_conf(conf_path: str) -> dict[str, Any]:
    """Parse *conf_path* (weewx.conf) and extract DB connection parameters.

    Navigates:
      - ``[DatabaseTypes][archive_mysql]`` for host, user, password, port
      - ``[Databases][archive_mysql][database_name]`` for the DB name

    Returns a dict with keys: host, port, user, password, db_name.

    Raises:
        FileNotFoundError: *conf_path* does not exist.
        KeyError: The expected sections/keys are absent from weewx.conf.
        ValueError: The port value cannot be parsed as an integer.
    """
    import os

    # Import here to avoid hard-coding configobj as a top-level dependency
    # in modules that don't need it.
    from configobj import ConfigObj  # type: ignore[import-untyped]

    if not os.path.exists(conf_path):
        raise FileNotFoundError(f"weewx.conf not found: {conf_path}")

    cfg = ConfigObj(conf_path, file_error=True)

    try:
        db_types = cfg["DatabaseTypes"]
        mysql_type = db_types["archive_mysql"]
        host = str(mysql_type.get("host", "localhost"))
        user = str(mysql_type.get("user", ""))
        password = str(mysql_type.get("password", ""))
        raw_port = mysql_type.get("port", "3306")
        port = int(raw_port)
    except KeyError as exc:
        raise KeyError(
            f"weewx.conf is missing expected section/key: {exc}. "
            "Verify that [DatabaseTypes][archive_mysql] is present."
        ) from exc
    except ValueError as exc:
        raise ValueError(
            f"weewx.conf [DatabaseTypes][archive_mysql] port is not an integer: {exc}"
        ) from exc

    try:
        databases = cfg["Databases"]
        archive_db = databases["archive_mysql"]
        db_name = str(archive_db.get("database_name", "weewx"))
    except KeyError:
        # Fall back to the conventional default if Databases section is absent.
        db_name = "weewx"

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "db_name": db_name,
    }


def _friendly_db_error(message: str) -> str:
    """Return a user-friendly error message for a DB connection failure.

    Maps common error patterns to plain-English explanations.  Always strips
    credentials from the raw SQLAlchemy message before logging or displaying.
    """
    import re

    # Strip credentials from the URL embedded in SQLAlchemy messages so we can
    # safely include the sanitised message in operator logs without leaking passwords.
    sanitised = re.sub(r"(://[^:]*:)[^@]+@", r"\1***@", message)

    msg_lower = sanitised.lower()

    if "access denied" in msg_lower or "1045" in sanitised:
        return "Could not connect to the database — the username or password is incorrect."
    if "unknown database" in msg_lower or "1049" in sanitised:
        return "Could not connect to the database — the database name was not found. Check the database name field."
    if "connection refused" in msg_lower or "2003" in sanitised:
        return "Could not reach the database server — check that the hostname and port are correct and that MariaDB/MySQL is running."
    if "timed out" in msg_lower or "2013" in sanitised:
        return "The database connection timed out — check that the hostname is correct and the server is reachable."
    if "name or service not known" in msg_lower or "nodename nor servname" in msg_lower:
        return "Could not find a database server at that hostname — check that the hostname is spelled correctly."

    return "Could not connect to the database — check your hostname, port, username, and password and try again."

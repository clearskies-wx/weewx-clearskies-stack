"""Tests for weewx_clearskies_config.wizard.db — URL building and weewx.conf parsing.

SQLAlchemy connection tests (test_connection) are not exercised here because
they require a live MariaDB instance.  All in-scope units are pure functions
or file-based parsers that work without a DB.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from weewx_clearskies_config.wizard.db import build_db_url, detect_from_weewx_conf


# ---------------------------------------------------------------------------
# build_db_url
# ---------------------------------------------------------------------------


def test_build_db_url_produces_pymysql_scheme():
    url = build_db_url("localhost", 3306, "weewx", "password", "weewxdb")
    assert url.startswith("mysql+pymysql://")


def test_build_db_url_includes_host_port_and_dbname():
    url = build_db_url("192.168.7.20", 3306, "weewx", "pass", "weewx")
    assert "192.168.7.20:3306" in url
    assert url.endswith("/weewx")


def test_build_db_url_percent_encodes_at_sign_in_password():
    """Password containing '@' would break URL parsing if not encoded."""
    url = build_db_url("localhost", 3306, "user", "p@ssw0rd", "db")
    # The encoded form of '@' is '%40'
    assert "%40" in url
    # The raw '@' must not appear in the password position
    # Verify by parsing — the host part must be 'localhost'
    parsed = urllib.parse.urlparse(url)
    assert parsed.hostname == "localhost"


def test_build_db_url_percent_encodes_colon_in_password():
    url = build_db_url("localhost", 3306, "user", "pa:ss", "db")
    assert "%3A" in url


def test_build_db_url_percent_encodes_slash_in_password():
    url = build_db_url("localhost", 3306, "user", "pa/ss", "db")
    assert "%2F" in url


def test_build_db_url_percent_encodes_at_sign_in_username():
    url = build_db_url("localhost", 3306, "user@domain", "pass", "db")
    assert "%40" in url
    parsed = urllib.parse.urlparse(url)
    assert parsed.hostname == "localhost"


def test_build_db_url_with_complex_special_chars_in_password_round_trips():
    """Special chars: @, :, /, #, ?, & all percent-encoded so URL remains parseable."""
    raw_password = "P@$$w0rd:with/special#chars?and&more"
    url = build_db_url("db.local", 3306, "user", raw_password, "weewx")
    parsed = urllib.parse.urlparse(url)
    # Decode the password component back
    userinfo = parsed.netloc.split("@")[0]  # user:encoded_password
    _, encoded_pw = userinfo.split(":", 1)
    decoded = urllib.parse.unquote(encoded_pw)
    assert decoded == raw_password


def test_build_db_url_uses_correct_port():
    url = build_db_url("localhost", 3307, "user", "pass", "db")
    assert ":3307/" in url


# ---------------------------------------------------------------------------
# detect_from_weewx_conf
# ---------------------------------------------------------------------------


def test_detect_from_weewx_conf_returns_correct_host(sample_weewx_conf: str):
    result = detect_from_weewx_conf(sample_weewx_conf)
    assert result["host"] == "192.168.7.20"


def test_detect_from_weewx_conf_returns_correct_port_as_int(sample_weewx_conf: str):
    result = detect_from_weewx_conf(sample_weewx_conf)
    assert result["port"] == 3306
    assert isinstance(result["port"], int)


def test_detect_from_weewx_conf_returns_correct_user(sample_weewx_conf: str):
    result = detect_from_weewx_conf(sample_weewx_conf)
    assert result["user"] == "weewx"


def test_detect_from_weewx_conf_returns_correct_password(sample_weewx_conf: str):
    result = detect_from_weewx_conf(sample_weewx_conf)
    assert result["password"] == "testpass123"


def test_detect_from_weewx_conf_returns_correct_db_name(sample_weewx_conf: str):
    result = detect_from_weewx_conf(sample_weewx_conf)
    assert result["db_name"] == "weewx"


def test_detect_from_weewx_conf_raises_file_not_found_for_missing_file():
    with pytest.raises(FileNotFoundError, match="weewx.conf not found"):
        detect_from_weewx_conf("/nonexistent/path/weewx.conf")


def test_detect_from_weewx_conf_raises_key_error_for_missing_database_types_section(
    tmp_path: Path,
):
    conf = tmp_path / "weewx.conf"
    conf.write_text("[Station]\nlatitude = 0\n", encoding="utf-8")
    with pytest.raises(KeyError, match="DatabaseTypes"):
        detect_from_weewx_conf(str(conf))


def test_detect_from_weewx_conf_raises_key_error_for_missing_archive_mysql_section(
    tmp_path: Path,
):
    conf = tmp_path / "weewx.conf"
    conf.write_text(
        "[DatabaseTypes]\n    [[archive_sqlite]]\n        driver = weedb.sqlite\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        detect_from_weewx_conf(str(conf))


def test_detect_from_weewx_conf_raises_value_error_for_non_integer_port(tmp_path: Path):
    conf = tmp_path / "weewx.conf"
    conf.write_text(
        "[DatabaseTypes]\n"
        "    [[archive_mysql]]\n"
        "        host = localhost\n"
        "        user = weewx\n"
        "        password = pass\n"
        "        port = not_a_number\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        detect_from_weewx_conf(str(conf))


def test_detect_from_weewx_conf_uses_default_db_name_when_databases_section_absent(
    tmp_path: Path,
):
    """When [Databases] section is absent, default db_name 'weewx' is used."""
    conf = tmp_path / "weewx.conf"
    conf.write_text(
        "[DatabaseTypes]\n"
        "    [[archive_mysql]]\n"
        "        host = localhost\n"
        "        user = weewx\n"
        "        password = pass\n"
        "        port = 3306\n",
        encoding="utf-8",
    )
    result = detect_from_weewx_conf(str(conf))
    assert result["db_name"] == "weewx"

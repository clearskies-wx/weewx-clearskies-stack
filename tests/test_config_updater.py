"""Tests for weewx_clearskies_config.config.updater — MANAGED REGION merge logic.

Critical correctness guarantee: the free-form region below MANAGED REGION END
must survive any number of update passes untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weewx_clearskies_config.config.updater import (
    MANAGED_BEGIN,
    MANAGED_END,
    update_column_mapping,
    update_managed_region,
    update_secrets,
)
from weewx_clearskies_config.config.reader import get_section, get_column_mapping


_FULL_CONF = f"""\
# Managed by weewx-clearskies-config on 2026-01-01.
{MANAGED_BEGIN}
[server]
bind_host = 127.0.0.1
bind_port = 8765

[database]
host = db.local
port = 3306
{MANAGED_END}
# Free-form region below — the configuration UI does not touch this.
[custom]
my_flag = true
# operator note: do not remove
"""


# ---------------------------------------------------------------------------
# update_managed_region — basic behaviour
# ---------------------------------------------------------------------------



def test_update_managed_region_updates_existing_key_in_section(tmp_path: Path):
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "server", {"bind_port": "9000"})
    result = conf.read_text(encoding="utf-8")
    assert "bind_port = 9000" in result



def test_update_managed_region_adds_new_key_to_existing_section(tmp_path: Path):
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "server", {"tls_enabled": "true"})
    result = conf.read_text(encoding="utf-8")
    assert "tls_enabled = true" in result



def test_update_managed_region_creates_new_section_when_absent(tmp_path: Path):
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "forecast", {"provider": "openmeteo"})
    result = conf.read_text(encoding="utf-8")
    assert "[forecast]" in result
    assert "provider = openmeteo" in result



def test_update_managed_region_preserves_managed_region_markers(tmp_path: Path):
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "server", {"bind_host": "0.0.0.0"})
    result = conf.read_text(encoding="utf-8")
    assert MANAGED_BEGIN in result
    assert MANAGED_END in result



def test_update_managed_region_preserves_free_form_region_after_end_marker(tmp_path: Path):
    """The operator's hand-written config below MANAGED REGION END must survive."""
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "server", {"bind_host": "0.0.0.0"})
    result = conf.read_text(encoding="utf-8")
    assert "[custom]" in result
    assert "my_flag = true" in result
    assert "operator note: do not remove" in result



def test_update_managed_region_preserves_free_form_region_after_multiple_updates(tmp_path: Path):
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    update_managed_region(conf, "server", {"bind_host": "::1"})
    update_managed_region(conf, "database", {"host": "newdb.local"})
    update_managed_region(conf, "forecast", {"provider": "nws"})
    result = conf.read_text(encoding="utf-8")
    assert "my_flag = true" in result
    assert "operator note: do not remove" in result



def test_update_managed_region_no_markers_treats_entire_file_as_managed(tmp_path: Path):
    """A hand-written config without markers should be updated in-place with markers added."""
    no_markers = "[server]\nbind_host = 127.0.0.1\nbind_port = 8765\n"
    conf = tmp_path / "api.conf"
    conf.write_text(no_markers, encoding="utf-8")
    update_managed_region(conf, "server", {"bind_port": "9876"})
    result = conf.read_text(encoding="utf-8")
    assert "bind_port = 9876" in result
    # Markers should now be present after first update
    assert MANAGED_BEGIN in result
    assert MANAGED_END in result


def test_update_managed_region_raises_for_empty_section_name(tmp_path: Path):
    # ValueError is raised before the write path — no configobj serialization involved.
    conf = tmp_path / "api.conf"
    conf.write_text(_FULL_CONF, encoding="utf-8")
    with pytest.raises(ValueError, match="section"):
        update_managed_region(conf, "  ", {"key": "value"})


def test_update_managed_region_raises_when_file_not_found(tmp_path: Path):
    # FileNotFoundError raised before any file read — no configobj serialization.
    missing = tmp_path / "ghost.conf"
    with pytest.raises(FileNotFoundError):
        update_managed_region(missing, "server", {"key": "value"})


# ---------------------------------------------------------------------------
# Round-trip: config_writer → reader → updater → reader
# ---------------------------------------------------------------------------



@pytest.mark.xfail(reason="ADR-038: write_api_conf raises NotImplementedError", raises=NotImplementedError)
def test_round_trip_write_read_update_read_via_real_modules(tmp_path: Path):
    """Write with config_writer, read via reader, update via updater, re-read."""
    from weewx_clearskies_config.wizard.state import WizardState
    from weewx_clearskies_config.wizard.config_writer import write_api_conf

    state = WizardState(
        db_host="192.168.1.1",
        db_port=3306,
        db_user="weewx",
        db_name="weewxdb",
        api_bind_host="127.0.0.1",
        api_bind_port=8765,
        providers={
            "forecast": "nws",
            "alerts": "nws_alerts",
            "aqi": "openweathermap_aqi",
            "earthquakes": "usgs",
            "radar": "rainviewer",
        },
        column_mapping={"outTemp": "outdoor_temperature"},
    )
    write_api_conf(state, tmp_path)

    before = get_section("api", "server", tmp_path)
    assert before["bind_host"] == "127.0.0.1"

    api_conf = tmp_path / "api.conf"
    update_managed_region(api_conf, "server", {"bind_host": "0.0.0.0"})

    after = get_section("api", "server", tmp_path)
    assert after["bind_host"] == "0.0.0.0"
    assert after["bind_port"] == "8765"  # unchanged key preserved


# ---------------------------------------------------------------------------
# update_secrets — text-only, no configobj write, not affected by the bug
# ---------------------------------------------------------------------------


def test_update_secrets_adds_new_key_to_secrets_env(tmp_path: Path):
    update_secrets("NEW_KEY", "new_value", tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "NEW_KEY=new_value" in content


def test_update_secrets_updates_existing_key_in_place(tmp_path: Path):
    (tmp_path / "secrets.env").write_text("EXISTING=old_value\n", encoding="utf-8")
    update_secrets("EXISTING", "new_value", tmp_path)
    lines = (tmp_path / "secrets.env").read_text(encoding="utf-8").splitlines()
    assert "EXISTING=new_value" in lines
    count = sum(1 for line in lines if line.startswith("EXISTING="))
    assert count == 1


def test_update_secrets_preserves_other_keys_unchanged(tmp_path: Path):
    (tmp_path / "secrets.env").write_text("A=alpha\nB=beta\n", encoding="utf-8")
    update_secrets("A", "new_alpha", tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "B=beta" in content


def test_update_secrets_raises_for_empty_key(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid secrets key"):
        update_secrets("", "value", tmp_path)


def test_update_secrets_raises_for_key_with_equals_sign(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid secrets key"):
        update_secrets("KEY=BAD", "value", tmp_path)


def test_update_secrets_raises_for_key_with_whitespace(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid secrets key"):
        update_secrets("KEY WITH SPACE", "value", tmp_path)


def test_update_secrets_creates_config_dir_when_absent(tmp_path: Path):
    nested = tmp_path / "new" / "dir"
    update_secrets("KEY", "val", nested)
    assert (nested / "secrets.env").exists()


# ---------------------------------------------------------------------------
# update_column_mapping
# ---------------------------------------------------------------------------



def test_update_column_mapping_writes_to_api_conf(tmp_path: Path):
    (tmp_path / "api.conf").write_text(
        f"{MANAGED_BEGIN}\n[server]\nbind_host = 127.0.0.1\n{MANAGED_END}\n",
        encoding="utf-8",
    )
    update_column_mapping(
        {"outTemp": "outdoor_temperature", "rain": "precipitation"}, tmp_path
    )
    result = get_column_mapping(tmp_path)
    assert result["outTemp"] == "outdoor_temperature"
    assert result["rain"] == "precipitation"



def test_update_column_mapping_omits_none_valued_entries(tmp_path: Path):
    (tmp_path / "api.conf").write_text(
        f"{MANAGED_BEGIN}\n[column_mapping]\noutTemp = outdoor_temperature\n{MANAGED_END}\n",
        encoding="utf-8",
    )
    update_column_mapping({"outTemp": None, "rain": "precipitation"}, tmp_path)
    result = get_column_mapping(tmp_path)
    assert "outTemp" not in result
    assert result["rain"] == "precipitation"


def test_update_column_mapping_raises_when_api_conf_absent(tmp_path: Path):
    # FileNotFoundError is raised before any configobj write.
    with pytest.raises(FileNotFoundError):
        update_column_mapping({"outTemp": "outdoor_temperature"}, tmp_path)

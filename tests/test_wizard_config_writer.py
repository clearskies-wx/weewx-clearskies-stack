"""Tests for weewx_clearskies_config.wizard.config_writer — config file generation.

All tests use tmp_path and a minimal WizardState.  No DB or HTTP required.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from weewx_clearskies_config.wizard.config_writer import (
    apply_wizard,
    write_api_conf,
    write_realtime_conf,
    write_secrets_env,
    write_stack_conf,
)
from weewx_clearskies_config.wizard.state import WizardState

_MANAGED_BEGIN = "# MANAGED REGION BEGIN"
_MANAGED_END = "# MANAGED REGION END"


def _minimal_state(**overrides) -> WizardState:
    """Return a WizardState with realistic values for testing."""
    defaults = dict(
        db_host="192.168.7.20",
        db_port=3306,
        db_user="weewx",
        db_password="s3cr3t!Pass",
        db_name="weewx",
        station_name="Home Weather Station",
        latitude=38.8894,
        longitude=-77.0352,
        altitude_meters=15.24,
        timezone="America/New_York",
        topology="same-host",
        api_bind_host="127.0.0.1",
        api_bind_port=8765,
        realtime_bind_host="127.0.0.1",
        realtime_bind_port=8766,
        providers={
            "forecast": "nws",
            "alerts": "nws_alerts",
            "aqi": "openweathermap_aqi",
            "earthquakes": "usgs",
            "radar": "rainviewer",
        },
        column_mapping={"outTemp": "outdoor_temperature"},
        api_keys={"openweathermap_aqi": {"api_key": "test_owm_key"}},
    )
    defaults.update(overrides)
    return WizardState(**defaults)


# ---------------------------------------------------------------------------
# write_api_conf — all xfail due to BUG A7
# ---------------------------------------------------------------------------

_XFAIL_BUG_A7 = pytest.mark.xfail(
    raises=NotImplementedError,
    reason="write_api_conf not yet implemented (BUG A7)",
    strict=True,
)


@_XFAIL_BUG_A7
def test_write_api_conf_creates_api_conf_file(tmp_path: Path):
    write_api_conf(_minimal_state(), tmp_path)
    assert (tmp_path / "api.conf").exists()


@_XFAIL_BUG_A7
def test_write_api_conf_includes_managed_region_begin_marker(tmp_path: Path):
    write_api_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert _MANAGED_BEGIN in content


@_XFAIL_BUG_A7
def test_write_api_conf_includes_managed_region_end_marker(tmp_path: Path):
    write_api_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert _MANAGED_END in content


@_XFAIL_BUG_A7
def test_write_api_conf_writes_server_section_with_bind_host_and_port(tmp_path: Path):
    write_api_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert "bind_host = 127.0.0.1" in content
    assert "bind_port = 8765" in content


@_XFAIL_BUG_A7
def test_write_api_conf_writes_database_section_without_password(tmp_path: Path):
    """DB password must NEVER appear in the .conf file — it lives in secrets.env."""
    state = _minimal_state(db_password="should_not_be_here")
    write_api_conf(state, tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert "should_not_be_here" not in content


@_XFAIL_BUG_A7
def test_write_api_conf_writes_column_mapping_section(tmp_path: Path):
    state = _minimal_state(
        column_mapping={"outTemp": "outdoor_temperature", "rain": "precipitation"}
    )
    write_api_conf(state, tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert "outTemp = outdoor_temperature" in content
    assert "rain = precipitation" in content


@_XFAIL_BUG_A7
def test_write_api_conf_writes_all_five_provider_domain_sections(tmp_path: Path):
    write_api_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    for domain in ("forecast", "alerts", "aqi", "earthquakes", "radar"):
        assert f"[{domain}]" in content


@_XFAIL_BUG_A7
def test_write_api_conf_returns_path_to_written_file(tmp_path: Path):
    result = write_api_conf(_minimal_state(), tmp_path)
    assert result == tmp_path / "api.conf"


# ---------------------------------------------------------------------------
# write_realtime_conf — all xfail due to BUG A7
# ---------------------------------------------------------------------------



def test_write_realtime_conf_creates_realtime_conf_file(tmp_path: Path):
    write_realtime_conf(_minimal_state(), tmp_path)
    assert (tmp_path / "realtime.conf").exists()



def test_write_realtime_conf_includes_managed_region_markers(tmp_path: Path):
    write_realtime_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert _MANAGED_BEGIN in content
    assert _MANAGED_END in content



def test_write_realtime_conf_writes_server_bind_address_and_port(tmp_path: Path):
    state = _minimal_state(realtime_bind_host="127.0.0.1", realtime_bind_port=8766)
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert "bind_host = 127.0.0.1" in content
    assert "bind_port = 8766" in content


def test_write_realtime_conf_writes_station_section_when_lat_lon_set(tmp_path: Path):
    """[station] section is written when both latitude and longitude are present (ADR-044)."""
    state = _minimal_state(
        latitude=38.8894,
        longitude=-77.0352,
        altitude_meters=15.24,
        timezone="America/New_York",
    )
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert "[station]" in content
    assert "38.8894" in content
    assert "-77.0352" in content
    assert "15.24" in content
    assert "America/New_York" in content


def test_write_realtime_conf_omits_station_section_when_lat_lon_are_none(tmp_path: Path):
    """[station] section must not be written when latitude or longitude is None (ADR-044)."""
    state = _minimal_state(latitude=None, longitude=None)
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert "[station]" not in content


def test_write_realtime_conf_omits_station_section_when_only_lat_is_none(tmp_path: Path):
    """Both lat and lon required; missing either means no [station] section (ADR-044)."""
    state = _minimal_state(latitude=None, longitude=-77.0352)
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert "[station]" not in content


def test_write_realtime_conf_station_altitude_defaults_to_zero_when_none(tmp_path: Path):
    """altitude_meters defaults to '0' in [station] when not provided (ADR-044)."""
    state = _minimal_state(latitude=38.8894, longitude=-77.0352, altitude_meters=None)
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    assert "[station]" in content
    assert "altitude_meters = 0" in content


def test_write_realtime_conf_station_section_appears_after_units_and_before_api(tmp_path: Path):
    """[station] must appear after [units] and before [api] in realtime.conf (ADR-044)."""
    state = _minimal_state(latitude=38.8894, longitude=-77.0352, api_address="http://127.0.0.1:8765")
    write_realtime_conf(state, tmp_path)
    content = (tmp_path / "realtime.conf").read_text(encoding="utf-8")
    units_pos = content.index("[units]")
    station_pos = content.index("[station]")
    api_pos = content.index("[api]")
    assert units_pos < station_pos < api_pos, (
        f"Expected [units] < [station] < [api], got positions {units_pos}, {station_pos}, {api_pos}"
    )


# ---------------------------------------------------------------------------
# write_stack_conf — all xfail due to BUG A7
# ---------------------------------------------------------------------------



def test_write_stack_conf_creates_stack_conf_file(tmp_path: Path):
    write_stack_conf(_minimal_state(), tmp_path)
    assert (tmp_path / "stack.conf").exists()



def test_write_stack_conf_includes_managed_region_markers(tmp_path: Path):
    write_stack_conf(_minimal_state(), tmp_path)
    content = (tmp_path / "stack.conf").read_text(encoding="utf-8")
    assert _MANAGED_BEGIN in content
    assert _MANAGED_END in content



def test_write_stack_conf_writes_station_name_and_coordinates(tmp_path: Path):
    state = _minimal_state(
        station_name="My Station",
        latitude=38.8894,
        longitude=-77.0352,
    )
    write_stack_conf(state, tmp_path)
    content = (tmp_path / "stack.conf").read_text(encoding="utf-8")
    assert "station_name = My Station" in content
    assert "38.8894" in content
    assert "-77.0352" in content


# ---------------------------------------------------------------------------
# write_secrets_env — pure string concatenation, no configobj, passes cleanly
# ---------------------------------------------------------------------------


def test_write_secrets_env_creates_secrets_env_file(tmp_path: Path):
    write_secrets_env(_minimal_state(), tmp_path)
    assert (tmp_path / "secrets.env").exists()


def test_write_secrets_env_does_not_contain_ini_section_headers(tmp_path: Path):
    """secrets.env must be KEY=VALUE format, never [section] headers."""
    write_secrets_env(_minimal_state(), tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert not re.search(r"^\[.*\]", content, re.MULTILINE), (
        "secrets.env must not contain .conf section headers"
    )


def test_write_secrets_env_includes_db_password(tmp_path: Path):
    state = _minimal_state(db_password="my_db_password!")
    write_secrets_env(state, tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    # Values are single-quoted for safe shell sourcing (Finding 4).
    assert "WEEWX_CLEARSKIES_DB_PASSWORD='my_db_password!'" in content


def test_write_secrets_env_includes_provider_api_keys(tmp_path: Path):
    state = _minimal_state(api_keys={"openweathermap_aqi": {"api_key": "myowmkey123"}})
    write_secrets_env(state, tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "myowmkey123" in content


def test_write_secrets_env_includes_proxy_secret_for_cross_host(tmp_path: Path):
    state = _minimal_state(topology="cross-host", proxy_secret="abc123def456" * 5 + "abcd")
    write_secrets_env(state, tmp_path)
    content = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "WEEWX_CLEARSKIES_PROXY_SECRET=" in content


def test_write_secrets_env_returns_path_to_written_file(tmp_path: Path):
    result = write_secrets_env(_minimal_state(), tmp_path)
    assert result == tmp_path / "secrets.env"


# ---------------------------------------------------------------------------
# apply_wizard — all xfail due to BUG A7 (calls all three write_*_conf)
# ---------------------------------------------------------------------------



def test_apply_wizard_writes_all_expected_conf_files(tmp_path: Path):
    result = apply_wizard(_minimal_state(), tmp_path)
    files = [Path(p).name for p in result["files_written"]]
    assert "api.conf" in files
    assert "realtime.conf" in files
    assert "stack.conf" in files



def test_apply_wizard_writes_secrets_env(tmp_path: Path):
    result = apply_wizard(_minimal_state(), tmp_path)
    assert len(result["secrets_written"]) == 1
    assert Path(result["secrets_written"][0]).name == "secrets.env"



def test_apply_wizard_all_written_files_exist_on_disk(tmp_path: Path):
    result = apply_wizard(_minimal_state(), tmp_path)
    for p in result["files_written"] + result["secrets_written"]:
        assert Path(p).exists(), f"Expected file missing: {p}"



def test_apply_wizard_api_conf_does_not_contain_db_password(tmp_path: Path):
    state = _minimal_state(db_password="never_in_conf")
    apply_wizard(state, tmp_path)
    content = (tmp_path / "api.conf").read_text(encoding="utf-8")
    assert "never_in_conf" not in content

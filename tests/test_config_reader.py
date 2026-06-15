"""Tests for weewx_clearskies_config.config.reader — .conf file parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from weewx_clearskies_config.config.reader import (
    COMPONENTS,
    get_all_sections,
    get_column_mapping,
    get_section,
    read_config,
)

_SAMPLE_API_CONF = """\
# MANAGED REGION BEGIN
[server]
bind_host = 127.0.0.1
bind_port = 8765

[database]
host = 192.168.7.20
port = 3306
user = weewx
name = weewx

[column_mapping]
outTemp = outdoor_temperature
outHumidity = outdoor_humidity

[forecast]
provider = nws
# MANAGED REGION END
# Free-form region below — the configuration UI does not touch this.
[custom_stuff]
manual_key = manual_value
"""

_SAMPLE_STACK_CONF = """\
# MANAGED REGION BEGIN
[ui]
station_name = Test Station
latitude = 38.8894
longitude = -77.0352
# MANAGED REGION END
"""


# ---------------------------------------------------------------------------
# read_config
# ---------------------------------------------------------------------------


def test_read_config_returns_none_when_file_absent(config_dir: Path):
    result = read_config("api", config_dir)
    assert result is None


def test_read_config_returns_configobj_for_existing_file(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = read_config("api", config_dir)
    assert result is not None


def test_read_config_parses_managed_region_sections(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    cfg = read_config("api", config_dir)
    assert "server" in cfg
    assert "database" in cfg
    assert "column_mapping" in cfg


def test_read_config_excludes_free_form_region_below_end_marker(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    cfg = read_config("api", config_dir)
    # [custom_stuff] lives below MANAGED REGION END — must not be visible
    assert "custom_stuff" not in cfg


def test_read_config_treats_entire_file_as_managed_when_no_markers(config_dir: Path):
    """Backward compat: hand-written configs without markers are fully managed."""
    no_markers = "[server]\nbind_host = 0.0.0.0\nbind_port = 9000\n"
    (config_dir / "api.conf").write_text(no_markers, encoding="utf-8")
    cfg = read_config("api", config_dir)
    assert cfg is not None
    assert "server" in cfg


def test_read_config_raises_for_unknown_component(config_dir: Path):
    with pytest.raises(ValueError, match="Unknown component"):
        read_config("nonexistent", config_dir)


def test_read_config_valid_components_are_api_and_stack(config_dir: Path):
    assert set(COMPONENTS) == {"api", "stack"}


# ---------------------------------------------------------------------------
# get_section
# ---------------------------------------------------------------------------


def test_get_section_returns_key_value_dict_for_known_section(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = get_section("api", "server", config_dir)
    assert result["bind_host"] == "127.0.0.1"
    assert result["bind_port"] == "8765"


def test_get_section_returns_empty_dict_when_section_absent(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = get_section("api", "nonexistent_section", config_dir)
    assert result == {}


def test_get_section_returns_empty_dict_when_file_absent(config_dir: Path):
    result = get_section("stack", "server", config_dir)
    assert result == {}


# ---------------------------------------------------------------------------
# get_all_sections
# ---------------------------------------------------------------------------


def test_get_all_sections_returns_dict_keyed_by_component(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    (config_dir / "stack.conf").write_text(_SAMPLE_STACK_CONF, encoding="utf-8")
    result = get_all_sections(config_dir)
    assert "api" in result
    assert "stack" in result


def test_get_all_sections_contains_top_level_sections_from_api_conf(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = get_all_sections(config_dir)
    assert "server" in result["api"]
    assert "database" in result["api"]


def test_get_all_sections_absent_component_returns_empty_dict(config_dir: Path):
    # Only write api.conf; stack is absent
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = get_all_sections(config_dir)
    assert result["stack"] == {}


# ---------------------------------------------------------------------------
# get_column_mapping
# ---------------------------------------------------------------------------


def test_get_column_mapping_returns_db_col_to_canonical_mapping(config_dir: Path):
    (config_dir / "api.conf").write_text(_SAMPLE_API_CONF, encoding="utf-8")
    result = get_column_mapping(config_dir)
    assert result["outTemp"] == "outdoor_temperature"
    assert result["outHumidity"] == "outdoor_humidity"


def test_get_column_mapping_returns_empty_dict_when_api_conf_absent(config_dir: Path):
    result = get_column_mapping(config_dir)
    assert result == {}


def test_get_column_mapping_returns_empty_dict_when_section_absent(config_dir: Path):
    no_mapping = "# MANAGED REGION BEGIN\n[server]\nbind_host = 127.0.0.1\n# MANAGED REGION END\n"
    (config_dir / "api.conf").write_text(no_mapping, encoding="utf-8")
    result = get_column_mapping(config_dir)
    assert result == {}

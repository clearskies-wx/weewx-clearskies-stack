"""Tests for weewx_clearskies_config.wizard.skin_import.

Covers: parse_skin_conf(), parse_skin_conf_text(), SkinImportError,
        section extraction, [Extras] key categorisation, silent skips,
        type coercion, and edge cases.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from weewx_clearskies_config.wizard.skin_import import (
    SkinImportError,
    parse_skin_conf,
    parse_skin_conf_text,
)

# ---------------------------------------------------------------------------
# Test fixture — representative Belchertown skin.conf content
# ---------------------------------------------------------------------------

BELCHERTOWN_FIXTURE = """\
[Extras]
    site_title = My Weather Station
    logo_image = /images/logo.png
    logo_image_dark = /images/logo-dark.png
    forecast_provider = aeris
    aeris_api_id = abc123
    aeris_api_secret = xyz789
    mqtt_websockets_host = broker.example.com
    mqtt_websockets_port = 8080
    mqtt_websockets_ssl = 0
    mqtt_websockets_topic = weather/loop
    facebook_enabled = 1
    twitter_enabled = 0
    social_share_html = Share on <a href="...">Facebook</a>
    radar_enabled = 1
    earthquake_enabled = 1
    earthquake_maxradiuskm = 1000
    manifest_name = My Weather
    manifest_short_name = Weather
    theme = auto
    theme_toggle_enabled = 1
    custom_unknown_key = some_value

[Units]
    [[Groups]]
        group_temperature = degree_F
        group_speed = mile_per_hour
        group_pressure = inHg
        group_rain = inch
        group_rainrate = inch_per_hour
        group_altitude = foot
        group_distance = mile
    [[StringFormats]]
        degree_F = %.1f
        inch = %.2f
        inHg = %.3f
        mile_per_hour = %.0f
    [[Labels]]
        degree_F = " °F"
        inch = " in"
        inHg = " inHg"
        mile_per_hour = " mph"
    [[Ordinates]]
        directions = N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW
    [[TimeFormats]]
        hour = %H:%M
        day = %X
        week = %X (%A)
        month = %x %X
        year = %x %X
        rainyear = %x %X
        current = %x %X
        ephem_day = %X
        ephem_year = %x %X
    [[DegreeDays]]
        heating_base = 65, degree_F
        cooling_base = 65, degree_F
    [[Trend]]
        time_delta = 10800
        time_grace = 300

[Labels]
    [[Generic]]
        outTemp = Outside Temperature
        inTemp = Inside Temperature
        outHumidity = Outside Humidity
        barometer = Barometer
        windSpeed = Wind Speed
        windDir = Wind Direction
        rain = Rain
        rainRate = Rain Rate
        UV = UV Index
        radiation = Solar Radiation

[Almanac]
    moon_phases = New, Waxing crescent, First quarter, Waxing gibbous, Full, Waning gibbous, Last quarter, Waning crescent

[CheetahGenerator]
    search_list_extensions = user.belchertown.getData
    [[SummaryByMonth]]
        [[[NOAA_month]]]
            template = NOAA/NOAA-%Y-%m.txt

[ImageGenerator]
    image_width = 600
    image_height = 360

[CopyGenerator]
    copy_once = favicon.ico, images/*, js/*, css/*

[Generators]
    generator_list = weewx.cheetahgenerator.CheetahGenerator, weewx.imagegenerator.ImageGenerator, weewx.reportengine.CopyGenerator
"""

MINIMAL_FIXTURE = """\
[Units]
    [[Groups]]
        group_temperature = degree_C
        group_speed = km_per_hour
"""

EMPTY_FIXTURE = ""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write_fixture(tmp_path: Path, content: str, name: str = "skin.conf") -> str:
    """Write *content* to a temp file and return its path as a string."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# test_parse_minimal
# ---------------------------------------------------------------------------


def test_parse_minimal(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, MINIMAL_FIXTURE)
    result = parse_skin_conf(path)

    assert result["units"]["groups"]["group_temperature"] == "degree_C"
    assert result["units"]["groups"]["group_speed"] == "km_per_hour"

    # Everything else should be empty / default, not raise KeyError
    assert result["labels"] == {}
    assert result["extras"]["branding"] == {}
    assert result["extras"]["social"] == {}
    assert result["extras"]["mqtt"] == {}
    assert result["extras"]["providers"] == {}
    assert result["extras"]["feature_toggles"] == {}
    assert result["extras"]["pwa"] == {}
    assert result["extras"]["theme"] == {}
    assert result["almanac"]["moon_phases"] == []
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# test_parse_full_belchertown
# ---------------------------------------------------------------------------


def test_parse_full_belchertown(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, BELCHERTOWN_FIXTURE)
    result = parse_skin_conf(path)

    # units.groups
    assert result["units"]["groups"]["group_temperature"] == "degree_F"
    assert result["units"]["groups"]["group_speed"] == "mile_per_hour"
    assert result["units"]["groups"]["group_pressure"] == "inHg"

    # units.string_formats
    assert result["units"]["string_formats"]["degree_F"] == "%.1f"
    assert result["units"]["string_formats"]["inch"] == "%.2f"

    # units.time_formats
    assert result["units"]["time_formats"]["hour"] == "%H:%M"
    assert result["units"]["time_formats"]["ephem_year"] == "%x %X"

    # units.degree_days — kept as string
    assert result["units"]["degree_days"]["heating_base"] == "65, degree_F"
    assert result["units"]["degree_days"]["cooling_base"] == "65, degree_F"

    # units.trend — integers
    assert result["units"]["trend"]["time_delta"] == 10800
    assert result["units"]["trend"]["time_grace"] == 300

    # labels
    assert result["labels"]["outTemp"] == "Outside Temperature"
    assert result["labels"]["UV"] == "UV Index"

    # extras.branding
    assert result["extras"]["branding"]["site_title"] == "My Weather Station"
    assert result["extras"]["branding"]["logo_image"] == "/images/logo.png"
    assert result["extras"]["branding"]["logo_image_dark"] == "/images/logo-dark.png"

    # extras.social
    assert result["extras"]["social"]["facebook_enabled"] == "1"
    assert result["extras"]["social"]["twitter_enabled"] == "0"
    assert "social_share_html" in result["extras"]["social"]

    # extras.mqtt
    assert result["extras"]["mqtt"]["mqtt_websockets_host"] == "broker.example.com"
    assert result["extras"]["mqtt"]["mqtt_websockets_port"] == "8080"
    assert result["extras"]["mqtt"]["mqtt_websockets_topic"] == "weather/loop"

    # extras.providers
    assert result["extras"]["providers"]["forecast_provider"] == "aeris"
    assert result["extras"]["providers"]["aeris_api_id"] == "abc123"
    assert result["extras"]["providers"]["aeris_api_secret"] == "xyz789"
    assert result["extras"]["providers"]["earthquake_maxradiuskm"] == "1000"

    # extras.pwa
    assert result["extras"]["pwa"]["manifest_name"] == "My Weather"
    assert result["extras"]["pwa"]["manifest_short_name"] == "Weather"

    # extras.theme
    assert result["extras"]["theme"]["theme"] == "auto"
    assert result["extras"]["theme"]["theme_toggle_enabled"] == "1"

    # almanac
    assert len(result["almanac"]["moon_phases"]) == 8
    assert result["almanac"]["moon_phases"][0] == "New"
    assert result["almanac"]["moon_phases"][4] == "Full"

    # unknown key goes to unmatched and generates a warning
    assert "custom_unknown_key" in result["extras"]["unmatched"]
    assert any("custom_unknown_key" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# test_cheetah_sections_silently_skipped
# ---------------------------------------------------------------------------


def test_cheetah_sections_silently_skipped(tmp_path: Path) -> None:
    content = """\
[CheetahGenerator]
    search_list_extensions = user.belchertown.getData

[ImageGenerator]
    image_width = 600

[CopyGenerator]
    copy_once = favicon.ico

[Generators]
    generator_list = weewx.cheetahgenerator.CheetahGenerator

[Units]
    [[Groups]]
        group_temperature = degree_F
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    # No warnings for Cheetah sections
    cheetah_warnings = [w for w in result["warnings"] if any(
        kw in w for kw in ("CheetahGenerator", "ImageGenerator", "CopyGenerator", "Generators")
    )]
    assert cheetah_warnings == []

    # Unit data still extracted correctly
    assert result["units"]["groups"]["group_temperature"] == "degree_F"


# ---------------------------------------------------------------------------
# test_unknown_extras_warned
# ---------------------------------------------------------------------------


def test_unknown_extras_warned(tmp_path: Path) -> None:
    content = """\
[Extras]
    completely_unknown_key_xyz = value1
    another_mystery_setting = value2
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    assert "completely_unknown_key_xyz" in result["extras"]["unmatched"]
    assert "another_mystery_setting" in result["extras"]["unmatched"]
    assert len(result["warnings"]) == 2
    assert any("completely_unknown_key_xyz" in w for w in result["warnings"])
    assert any("another_mystery_setting" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# test_extras_categorization
# ---------------------------------------------------------------------------


def test_extras_categorization(tmp_path: Path) -> None:
    """Verify pattern-matching priority: social _enabled beats feature_toggles."""
    content = """\
[Extras]
    facebook_enabled = 1
    twitter_enabled = 0
    instagram_enabled = 1
    youtube_enabled = 1
    radar_enabled = 1
    earthquake_enabled = 1
    mqtt_websockets_host = broker.example.com
    aeris_api_id = abc123
    aeris_api_secret = xyz789
    manifest_name = My Weather
    theme = dark
    site_title = Test Station
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    # Social _enabled keys must go to social, NOT feature_toggles
    social = result["extras"]["social"]
    feature_toggles = result["extras"]["feature_toggles"]

    assert "facebook_enabled" in social
    assert "twitter_enabled" in social
    assert "instagram_enabled" in social
    assert "youtube_enabled" in social

    assert "facebook_enabled" not in feature_toggles
    assert "twitter_enabled" not in feature_toggles

    # Non-social _enabled keys go to feature_toggles
    assert "radar_enabled" in feature_toggles
    assert "earthquake_enabled" in feature_toggles

    # mqtt
    assert "mqtt_websockets_host" in result["extras"]["mqtt"]

    # providers — suffix _api_id / _api_secret
    assert "aeris_api_id" in result["extras"]["providers"]
    assert "aeris_api_secret" in result["extras"]["providers"]

    # pwa
    assert "manifest_name" in result["extras"]["pwa"]

    # theme
    assert "theme" in result["extras"]["theme"]

    # branding
    assert "site_title" in result["extras"]["branding"]

    # No warnings for matched keys
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# test_missing_sections
# ---------------------------------------------------------------------------


def test_missing_sections(tmp_path: Path) -> None:
    """Empty skin.conf — all sub-dicts return empty, no KeyError raised."""
    path = _write_fixture(tmp_path, EMPTY_FIXTURE)
    result = parse_skin_conf(path)

    assert result["units"]["groups"] == {}
    assert result["units"]["labels"] == {}
    assert result["units"]["string_formats"] == {}
    assert result["units"]["ordinates"]["directions"] == []
    assert result["units"]["time_formats"] == {}
    assert result["units"]["degree_days"] == {}
    assert result["units"]["trend"] == {}
    assert result["units"]["timezone"] is None
    assert result["labels"] == {}
    assert result["extras"]["branding"] == {}
    assert result["almanac"]["moon_phases"] == []
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# test_invalid_configobj
# ---------------------------------------------------------------------------


def test_invalid_configobj_raises_skin_import_error(tmp_path: Path) -> None:
    # A line with a key but no = sign inside a section can trigger a parse error.
    # configobj is quite forgiving, so we use a deeply malformed structure.
    malformed = """\
[Section
    key = value
"""
    path = _write_fixture(tmp_path, malformed)
    with pytest.raises(SkinImportError):
        parse_skin_conf(path)


# ---------------------------------------------------------------------------
# test_file_not_found
# ---------------------------------------------------------------------------


def test_file_not_found_raises_file_not_found_error(tmp_path: Path) -> None:
    missing = str(tmp_path / "nonexistent_skin.conf")
    with pytest.raises(FileNotFoundError):
        parse_skin_conf(missing)


# ---------------------------------------------------------------------------
# test_parse_text_variant
# ---------------------------------------------------------------------------


def test_parse_text_variant() -> None:
    """parse_skin_conf_text works identically to parse_skin_conf on same content."""
    result = parse_skin_conf_text(BELCHERTOWN_FIXTURE)

    assert result["units"]["groups"]["group_temperature"] == "degree_F"
    assert result["labels"]["outTemp"] == "Outside Temperature"
    assert result["extras"]["branding"]["site_title"] == "My Weather Station"
    assert result["extras"]["mqtt"]["mqtt_websockets_host"] == "broker.example.com"
    assert len(result["almanac"]["moon_phases"]) == 8
    assert any("custom_unknown_key" in w for w in result["warnings"])


def test_parse_text_variant_minimal() -> None:
    result = parse_skin_conf_text(MINIMAL_FIXTURE)
    assert result["units"]["groups"]["group_temperature"] == "degree_C"
    assert result["warnings"] == []


def test_parse_text_variant_invalid_raises_skin_import_error() -> None:
    malformed = "[Section\n    key = value\n"
    with pytest.raises(SkinImportError):
        parse_skin_conf_text(malformed)


# ---------------------------------------------------------------------------
# test_ordinates_parsing
# ---------------------------------------------------------------------------


def test_ordinates_parsing(tmp_path: Path) -> None:
    content = """\
[Units]
    [[Ordinates]]
        directions = N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    directions = result["units"]["ordinates"]["directions"]
    assert isinstance(directions, list)
    assert len(directions) == 16
    assert directions[0] == "N"
    assert directions[4] == "E"
    assert directions[8] == "S"
    assert directions[12] == "W"
    assert directions[15] == "NNW"


# ---------------------------------------------------------------------------
# test_trend_integer_parsing
# ---------------------------------------------------------------------------


def test_trend_integer_parsing(tmp_path: Path) -> None:
    content = """\
[Units]
    [[Trend]]
        time_delta = 10800
        time_grace = 300
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    assert isinstance(result["units"]["trend"]["time_delta"], int)
    assert result["units"]["trend"]["time_delta"] == 10800
    assert isinstance(result["units"]["trend"]["time_grace"], int)
    assert result["units"]["trend"]["time_grace"] == 300


# ---------------------------------------------------------------------------
# test_labels_singular_plural
# ---------------------------------------------------------------------------


def test_labels_singular_plural(tmp_path: Path) -> None:
    """ConfigObj list values in [[Labels]] are joined to a string."""
    # ConfigObj will parse  degree_F = °, °F  as a list ["°", "°F"]
    # We need to write the file with a comma to trigger list parsing.
    content = """\
[Units]
    [[Labels]]
        degree_F = °, °F
        inch = " in"
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    labels = result["units"]["labels"]
    # degree_F should be a string (joined from list)
    assert isinstance(labels["degree_F"], str)
    # inch is a plain string
    assert isinstance(labels["inch"], str)
    # The joined value must not be empty
    assert labels["degree_F"] != ""


# ---------------------------------------------------------------------------
# test_degree_days_kept_as_string
# ---------------------------------------------------------------------------


def test_degree_days_kept_as_string(tmp_path: Path) -> None:
    content = """\
[Units]
    [[DegreeDays]]
        heating_base = 65, degree_F
        cooling_base = 65, degree_F
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    # Values must be strings, not ints or parsed tuples.
    # ConfigObj parses "65, degree_F" as a list; the parser joins it back.
    heating = result["units"]["degree_days"]["heating_base"]
    cooling = result["units"]["degree_days"]["cooling_base"]

    assert isinstance(heating, str)
    assert isinstance(cooling, str)
    assert not isinstance(heating, int)
    assert not isinstance(cooling, int)
    assert "65" in heating
    assert "degree_F" in heating
    assert "65" in cooling
    assert "degree_F" in cooling


# ---------------------------------------------------------------------------
# test_std_sections_silently_skipped
# ---------------------------------------------------------------------------


def test_std_sections_silently_skipped(tmp_path: Path) -> None:
    """Sections starting with 'Std' are silently ignored, no warnings."""
    content = """\
[StdReport]
    HTML_ROOT = public_html

[StdCalibrate]
    [[Corrections]]
        outTemp = outTemp + 0.5

[Units]
    [[Groups]]
        group_temperature = degree_F
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    # No warnings for Std* sections
    std_warnings = [w for w in result["warnings"] if "Std" in w]
    assert std_warnings == []

    # Unit data extracted correctly
    assert result["units"]["groups"]["group_temperature"] == "degree_F"


# ---------------------------------------------------------------------------
# test_texts_section_extracted
# ---------------------------------------------------------------------------


def test_texts_section_extracted(tmp_path: Path) -> None:
    content = """\
[Texts]
    "Current Conditions" = "Aktuelle Bedingungen"
    "Daily Summary" = "Tageszusammenfassung"
"""
    path = _write_fixture(tmp_path, content)
    result = parse_skin_conf(path)

    # texts key present; no errors
    assert isinstance(result["texts"], dict)

"""
Unit tests for the Clear Skies config registry.

Covers:
  1. Registry population (all 8 sections, domain groups, duplicate detection)
  2. Field queries (attributes, frozen immutability, options)
  3. Validation (required, min/max, pattern, secret sentinel)
  4. Value extraction (known keys only, boolean, secret exclusion)
  5. Save dispatch (correct backend called per config_target)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from weewx_clearskies_config.registry import (
    ConfigField,
    DuplicateSectionError,
    FieldOption,
    SectionDef,
    ValidationRule,
    extract_field_values,
    registry,
    save_field_values,
    validate_form_against_fields,
)


# ---------------------------------------------------------------------------
# 1. Registry population
# ---------------------------------------------------------------------------


def test_all_7_sections_registered():
    """All 7 declared sections must be in the registry."""
    expected_section_ids = {
        "earthquakes",
        "analytics",
        "webcam",
        "branding",
        "pages",
        "tls",
        "sky_classification",
    }
    registered = {s.section_id for g in registry.get_all_domain_groups() for s in registry.get_sections_for_group(g)}
    assert expected_section_ids.issubset(registered)


def test_get_fields_for_section_returns_correct_count():
    """Each section should have the expected number of fields."""
    counts = {
        "earthquakes": 3,
        "analytics": 2,
        "webcam": 4,
        "branding": 9,
        "pages": 1,
        "tls": 7,
        "sky_classification": 6,
    }
    for section_id, expected_count in counts.items():
        fields = registry.get_fields_for_section(section_id)
        assert len(fields) == expected_count, (
            f"Section '{section_id}': expected {expected_count} fields, got {len(fields)}"
        )


def test_get_all_domain_groups_returns_expected_groups():
    """All four domain groups used in declarations should be returned."""
    groups = registry.get_all_domain_groups()
    assert "dashboard" in groups
    assert "appearance" in groups
    assert "advanced" in groups


def test_get_sections_for_group_returns_correct_sections():
    """Spot-check: dashboard group contains earthquakes and webcam."""
    dashboard_sections = {s.section_id for s in registry.get_sections_for_group("dashboard")}
    assert "earthquakes" in dashboard_sections
    assert "webcam" in dashboard_sections
    assert "pages" in dashboard_sections


def test_get_sections_for_group_appearance():
    """Appearance group contains analytics, branding."""
    appearance_sections = {s.section_id for s in registry.get_sections_for_group("appearance")}
    assert "analytics" in appearance_sections
    assert "branding" in appearance_sections


def test_get_sections_for_group_advanced():
    """Advanced group contains tls and sky_classification."""
    advanced_sections = {s.section_id for s in registry.get_sections_for_group("advanced")}
    assert "tls" in advanced_sections
    assert "sky_classification" in advanced_sections


def test_duplicate_section_raises_value_error():
    """Registering the same section_id twice must raise DuplicateSectionError."""
    from weewx_clearskies_config.registry import ConfigRegistry

    fresh_registry = ConfigRegistry()
    section = SectionDef(
        section_id="test_dup",
        display_name="Test Duplicate",
        domain_group="dashboard",
        config_source="stack.conf",
    )
    field = ConfigField(
        field_id="test_dup.field1",
        field_type="text",
        label="Field 1",
        config_target="stack.conf:test_dup",
        config_key="field1",
    )
    fresh_registry.register_section(section, (field,))
    with pytest.raises(DuplicateSectionError):
        fresh_registry.register_section(section, (field,))


# ---------------------------------------------------------------------------
# 2. Field queries
# ---------------------------------------------------------------------------


def test_earthquakes_radius_km_field_attributes():
    """earthquakes.radius_km must have default='250', field_type='number'."""
    fields = registry.get_fields_for_section("earthquakes")
    radius_field = next(f for f in fields if f.field_id == "earthquakes.radius_km")
    assert radius_field.default == "250"
    assert radius_field.field_type == "number"
    assert radius_field.config_key == "radius_km"


def test_config_field_is_frozen():
    """ConfigField is a frozen dataclass — attribute assignment must raise FrozenInstanceError."""
    field = ConfigField(
        field_id="test.frozen",
        field_type="text",
        label="Test",
        config_target="stack.conf:test",
        config_key="frozen",
    )
    with pytest.raises(FrozenInstanceError):
        field.label = "Modified"  # type: ignore[misc]


def test_branding_accent_radio_swatch_options():
    """branding.accent must be a radio_swatch with 6 color options."""
    fields = registry.get_fields_for_section("branding")
    accent_field = next(f for f in fields if f.field_id == "branding.accent")
    assert accent_field.field_type == "radio_swatch"
    option_values = {opt.value for opt in accent_field.options}
    assert option_values == {"blue", "teal", "indigo", "purple", "green", "amber"}


def test_theme_mode_contains_auto_sunrise_sunset():
    """Theme mode options must include 'auto-sunrise-sunset' (not the truncated 'auto-sunrise')."""
    fields = registry.get_fields_for_section("branding")
    theme_field = next(f for f in fields if f.field_id == "branding.default_theme_mode")
    option_values = {opt.value for opt in theme_field.options}
    assert "auto-sunrise-sunset" in option_values
    # Guard against the known truncation bug
    assert "auto-sunrise" not in option_values


def test_tls_mode_includes_all_5_modes():
    """TLS mode must declare all 5 modes per OPERATIONS-MANUAL §4.1."""
    fields = registry.get_fields_for_section("tls")
    mode_field = next(f for f in fields if f.field_id == "tls.mode")
    option_values = {opt.value for opt in mode_field.options}
    required_modes = {"self-signed", "acme_http01", "acme_dns01", "manual", "behind_proxy"}
    assert required_modes == option_values


# ---------------------------------------------------------------------------
# 3. Validation pass/fail
# ---------------------------------------------------------------------------

# A minimal set of fields for validation testing
_REQUIRED_FIELD = ConfigField(
    field_id="test.required_field",
    field_type="text",
    label="Required Field",
    validation=(ValidationRule("required", None),),
    config_target="stack.conf:test",
    config_key="required_field",
)

_NUMBER_FIELD = ConfigField(
    field_id="test.num_field",
    field_type="number",
    label="Number Field",
    validation=(
        ValidationRule("min", 1),
        ValidationRule("max", 100),
    ),
    config_target="stack.conf:test",
    config_key="num_field",
)

_PATTERN_FIELD = ConfigField(
    field_id="test.pattern_field",
    field_type="text",
    label="Pattern Field",
    validation=(ValidationRule("pattern", r"G-[A-Za-z0-9]+"),),
    config_target="stack.conf:test",
    config_key="pattern_field",
)

_SECRET_FIELD = ConfigField(
    field_id="test.secret_field",
    field_type="password",
    label="Secret Field",
    is_secret=True,
    validation=(ValidationRule("required", None),),
    config_target="secrets.env",
    config_key="secret_field",
)


def test_validate_missing_required_field_returns_error():
    errors = validate_form_against_fields({}, (_REQUIRED_FIELD,))
    assert len(errors) == 1
    assert "Required Field" in errors[0]


def test_validate_empty_required_field_returns_error():
    errors = validate_form_against_fields({"required_field": ""}, (_REQUIRED_FIELD,))
    assert len(errors) == 1


def test_validate_present_required_field_passes():
    errors = validate_form_against_fields({"required_field": "hello"}, (_REQUIRED_FIELD,))
    assert errors == []


def test_validate_number_below_min_returns_error():
    errors = validate_form_against_fields({"num_field": "0"}, (_NUMBER_FIELD,))
    assert any("Number Field" in e for e in errors)


def test_validate_number_above_max_returns_error():
    errors = validate_form_against_fields({"num_field": "200"}, (_NUMBER_FIELD,))
    assert any("Number Field" in e for e in errors)


def test_validate_number_in_range_passes():
    errors = validate_form_against_fields({"num_field": "50"}, (_NUMBER_FIELD,))
    assert errors == []


def test_validate_pattern_mismatch_returns_error():
    errors = validate_form_against_fields({"pattern_field": "not-valid"}, (_PATTERN_FIELD,))
    assert len(errors) == 1
    assert "Pattern Field" in errors[0]


def test_validate_pattern_match_passes():
    errors = validate_form_against_fields({"pattern_field": "G-ABC123"}, (_PATTERN_FIELD,))
    assert errors == []


def test_validate_valid_data_returns_empty_list():
    form = {
        "required_field": "hello",
        "num_field": "42",
        "pattern_field": "G-XYZ",
    }
    errors = validate_form_against_fields(form, (_REQUIRED_FIELD, _NUMBER_FIELD, _PATTERN_FIELD))
    assert errors == []


def test_validate_secret_with_unchanged_sentinel_skips_validation():
    """Secret field with '_unchanged' sentinel must not produce a 'required' error."""
    form = {"secret_field": "_unchanged"}
    errors = validate_form_against_fields(form, (_SECRET_FIELD,))
    assert errors == []


def test_validate_secret_with_real_value_passes():
    """Secret field with a non-sentinel value must validate normally."""
    form = {"secret_field": "mysecrettoken"}
    errors = validate_form_against_fields(form, (_SECRET_FIELD,))
    assert errors == []


def test_validate_secret_empty_without_sentinel_returns_error():
    """Secret field that is empty (not sentinel) must trigger required error."""
    form = {"secret_field": ""}
    errors = validate_form_against_fields(form, (_SECRET_FIELD,))
    assert len(errors) == 1


def test_validate_real_earthquake_fields_pass():
    """Spot-check using the live earthquakes declaration fields."""
    fields = registry.get_fields_for_section("earthquakes")
    form = {
        "radius_km": "250",
        "min_magnitude": "2.0",
        "default_days": "30",
    }
    errors = validate_form_against_fields(form, fields)
    assert errors == []


# ---------------------------------------------------------------------------
# 4. Value extraction
# ---------------------------------------------------------------------------

_EXTRACT_FIELDS = (
    ConfigField(
        field_id="test.name",
        field_type="text",
        label="Name",
        config_target="stack.conf:test",
        config_key="name",
    ),
    ConfigField(
        field_id="test.enabled",
        field_type="boolean",
        label="Enabled",
        config_target="stack.conf:test",
        config_key="enabled",
    ),
    ConfigField(
        field_id="test.secret",
        field_type="password",
        label="Secret",
        is_secret=True,
        config_target="secrets.env",
        config_key="secret",
    ),
    ConfigField(
        field_id="test.tags",
        field_type="checkbox_group",
        label="Tags",
        config_target="stack.conf:test",
        config_key="tags",
    ),
)


def test_extract_extracts_only_known_keys():
    form = {"name": "Alice", "unknown_extra": "should_be_dropped"}
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert "name" in result
    assert "unknown_extra" not in result


def test_extract_drops_unknown_form_keys_silently():
    form = {"unknown_key": "foo", "another_mystery": "bar"}
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result.get("unknown_key") is None
    assert result.get("another_mystery") is None


def test_extract_boolean_present_is_true():
    form = {"enabled": "on"}  # HTML checkbox sends a value when checked
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result["enabled"] is True


def test_extract_boolean_absent_is_false():
    form = {}  # unchecked checkbox: key absent from form_data
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result["enabled"] is False


def test_extract_secret_field_excluded():
    form = {"name": "Bob", "secret": "topsecret"}
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert "secret" not in result


def test_extract_checkbox_group_returns_list():
    form = {"tags": ["alpha", "beta"]}
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result["tags"] == ["alpha", "beta"]


def test_extract_checkbox_group_absent_returns_empty_list():
    form = {}
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result["tags"] == []


def test_extract_checkbox_group_single_value_returns_list():
    form = {"tags": "alpha"}  # single string, not yet a list
    result = extract_field_values(form, _EXTRACT_FIELDS)
    assert result["tags"] == ["alpha"]


# ---------------------------------------------------------------------------
# 5. Save dispatch
# ---------------------------------------------------------------------------

_EARTHQUAKES_SECTION_DEF = SectionDef(
    section_id="earthquakes",
    display_name="Earthquake Settings",
    domain_group="dashboard",
    config_source="stack.conf",
)

_BRANDING_SECTION_DEF = SectionDef(
    section_id="branding",
    display_name="Branding",
    domain_group="appearance",
    config_source="branding.json",
)

_PAGES_SECTION_DEF = SectionDef(
    section_id="pages",
    display_name="Pages Visibility",
    domain_group="dashboard",
    config_source="pages.json",
)

_TLS_SECTION_DEF = SectionDef(
    section_id="tls",
    display_name="TLS",
    domain_group="advanced",
    config_source="stack.conf",
)

_SKY_CLASSIFICATION_SECTION_DEF = SectionDef(
    section_id="sky_classification",
    display_name="Sky Classification",
    domain_group="advanced",
    config_source="api.conf",
)


def test_save_dispatch_stack_conf_calls_update_managed_region(tmp_path: Path):
    """stack.conf sections dispatch to update_managed_region with correct path and section."""
    values = {"radius_km": "300", "min_magnitude": "2.5", "default_days": "7"}
    conf_file = tmp_path / "stack.conf"
    # Create the file so update_managed_region doesn't raise FileNotFoundError
    conf_file.write_text("[earthquakes]\nradius_km = 250\n", encoding="utf-8")

    with patch(
        "weewx_clearskies_config.registry.validation.update_managed_region"
    ) as mock_umr:
        save_field_values(values, _EARTHQUAKES_SECTION_DEF, str(tmp_path))
        mock_umr.assert_called_once_with(tmp_path / "stack.conf", "earthquakes", values)


def test_save_dispatch_api_conf_calls_update_managed_region(tmp_path: Path):
    """api.conf sections dispatch to update_managed_region with the api.conf path."""
    values = {"scatter_few_max": "0.97"}
    conf_file = tmp_path / "api.conf"
    conf_file.write_text("[sky_classification]\nscatter_few_max = 0.97\n", encoding="utf-8")

    with patch(
        "weewx_clearskies_config.registry.validation.update_managed_region"
    ) as mock_umr:
        save_field_values(values, _SKY_CLASSIFICATION_SECTION_DEF, str(tmp_path))
        mock_umr.assert_called_once_with(tmp_path / "api.conf", "sky_classification", values)


def test_save_dispatch_branding_json_calls_update_branding(tmp_path: Path):
    """branding.json sections dispatch to update_branding with the config_dir path."""
    values = {"site_title": "My Station", "accent": "blue"}

    with patch(
        "weewx_clearskies_config.registry.validation.update_branding"
    ) as mock_ub:
        save_field_values(values, _BRANDING_SECTION_DEF, str(tmp_path))
        mock_ub.assert_called_once_with(tmp_path, values)


def test_save_dispatch_pages_json_calls_update_pages(tmp_path: Path):
    """pages.json sections dispatch to update_pages with the hidden pages list."""
    values = {"hidden_pages": ["forecast", "charts"]}

    with patch(
        "weewx_clearskies_config.registry.validation.update_pages"
    ) as mock_up:
        save_field_values(values, _PAGES_SECTION_DEF, str(tmp_path))
        mock_up.assert_called_once_with(tmp_path, ["forecast", "charts"])


def test_save_dispatch_pages_json_empty_list(tmp_path: Path):
    """pages.json section with no hidden pages passes empty list to update_pages."""
    values = {"hidden_pages": []}

    with patch(
        "weewx_clearskies_config.registry.validation.update_pages"
    ) as mock_up:
        save_field_values(values, _PAGES_SECTION_DEF, str(tmp_path))
        mock_up.assert_called_once_with(tmp_path, [])


def test_save_dispatch_unknown_target_raises_value_error():
    """A section whose first field has an unrecognised config_target must raise ValueError."""
    import sys
    from weewx_clearskies_config.registry import ConfigRegistry

    bad_registry = ConfigRegistry()
    bad_section = SectionDef(
        section_id="bad_section_unknown",
        display_name="Bad Section",
        domain_group="dashboard",
        config_source="unknown.conf",
    )
    bad_field = ConfigField(
        field_id="bad_section_unknown.field1",
        field_type="text",
        label="Field",
        config_target="unknown.conf:whatever",
        config_key="field1",
    )
    bad_registry.register_section(bad_section, (bad_field,))

    # save_field_values does `from .registry import registry as _registry` at call time.
    # Patch the `registry` attribute on the actual registry sub-module object.
    registry_submodule = sys.modules["weewx_clearskies_config.registry.registry"]
    with patch.object(registry_submodule, "registry", bad_registry):
        with pytest.raises(ValueError, match="unknown.conf:whatever"):
            save_field_values({"field1": "value"}, bad_section, "/tmp/fake")

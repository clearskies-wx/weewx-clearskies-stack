"""
Frozen dataclasses for the Clear Skies config registry.

ConfigField, FieldOption, ValidationRule, and Condition are all frozen
(immutable) so they can be safely shared across threads and cached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldOption:
    """A single option in a select, radio, radio_swatch, or checkbox_group field."""

    value: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ValidationRule:
    """
    A single validation constraint applied to a field value.

    rule_type is one of: required, min, max, step, pattern, one_of,
    max_length, max_file_size.
    """

    rule_type: str
    value: Any


@dataclass(frozen=True)
class Condition:
    """
    A conditional visibility rule.

    The field identified by field_id controls whether the field bearing
    this condition is shown.  operator is one of: eq, ne, in.
    Multiple Condition objects on a single field are treated as OR.
    """

    field_id: str
    operator: str  # "eq", "ne", "in"
    value: Any


@dataclass(frozen=True)
class ConfigField:
    """
    A single configurable field in the admin UI or setup wizard.

    field_id must be globally unique (e.g. "earthquakes.radius_km").
    field_type must be one of the 11 supported types:
        text, url, number, boolean, select, radio, password,
        file_or_url, radio_swatch, textarea, checkbox_group
    """

    field_id: str
    field_type: str
    label: str
    help_text: str = ""
    wizard_help: str = ""
    placeholder: str = ""
    default: Any = None
    options: tuple[FieldOption, ...] = ()
    validation: tuple[ValidationRule, ...] = ()
    config_target: str = ""
    config_key: str = ""
    is_secret: bool = False
    secret_env_key: str = ""
    conditions: tuple[Condition, ...] = ()
    wizard_visible: bool = True
    admin_visible: bool = True
    admin_landing_display: bool = False
    grid_column: str = "full"  # "full" or "half"

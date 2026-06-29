"""
weewx_clearskies_config.registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Public API for the Clear Skies config registry.

Importing this package automatically populates the registry singleton with
all field declarations (via `from . import declarations` at the bottom).

Typical usage
-------------
    from weewx_clearskies_config.registry import registry, ConfigField

    fields = registry.get_fields_for_section("earthquakes")
"""

from .fields import ConfigField, FieldOption, ValidationRule, Condition
from .sections import SectionDef, WizardStepDef
from .registry import ConfigRegistry, DuplicateSectionError, DuplicateStepError, registry
from .validation import validate_form_against_fields, extract_field_values, save_field_values

__all__ = [
    "ConfigField",
    "FieldOption",
    "ValidationRule",
    "Condition",
    "SectionDef",
    "WizardStepDef",
    "ConfigRegistry",
    "DuplicateSectionError",
    "DuplicateStepError",
    "registry",
    "validate_form_against_fields",
    "extract_field_values",
    "save_field_values",
]

# Populate the registry singleton at import time.
# This must come after all symbols are importable to avoid circular imports.
from . import declarations  # noqa: E402, F401

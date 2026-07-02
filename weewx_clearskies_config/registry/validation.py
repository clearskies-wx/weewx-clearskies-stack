"""
Validation and persistence helpers for the Clear Skies config registry.

Three public functions:
  - validate_form_against_fields: check form_data against ConfigField.validation rules
  - extract_field_values: pull keyed values from form_data, handling type coercions
  - save_field_values: dispatch extracted values to the correct backend writer
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from weewx_clearskies_config.config.updater import (
    update_branding,
    update_managed_region,
    update_pages,
)
from weewx_clearskies_config.i18n import get_current_locale, translate

from .fields import ConfigField, ValidationRule
from .sections import SectionDef


def _(key: str) -> str:
    """Translate *key* using the current request's wizard/admin UI locale.

    Python-code counterpart to the Jinja2 ``_()`` global — see the identical
    helper in wizard/routes.py and admin/routes.py for the full rationale.
    field.label itself is also passed through this so a translated field
    name appears in the validation message, matching what the render_field
    macro (macros/form_fields.html) shows for the same field on-screen.
    """
    return translate(key, get_current_locale())

logger = logging.getLogger(__name__)


def validate_form_against_fields(
    form_data: dict[str, str],
    fields: tuple[ConfigField, ...],
) -> list[str]:
    """
    Validate form_data against field ValidationRule tuples.
    Returns a list of human-readable error strings.
    Empty list means validation passed.

    Checks per rule_type:
    - required:       field absent or empty string
    - min:            float(value) < float(rule.value)
    - max:            float(value) > float(rule.value)
    - step:           (float(value) - min) % float(rule.value) != 0 (if min rule present)
    - pattern:        not re.fullmatch(rule.value, value)
    - one_of:         value not in rule.value (rule.value is a tuple of allowed strings)
    - max_length:     len(value) > int(rule.value)
    - max_file_size:  deferred to route handler — skipped here

    Secret fields with value "_unchanged" are skipped entirely.
    """
    errors: list[str] = []

    for field in fields:
        value = form_data.get(field.config_key, "")

        # Skip secret fields when the sentinel value is present
        if field.is_secret and value == "_unchanged":
            continue

        # Find the min rule value (needed for step validation)
        min_val: float | None = None
        for rule in field.validation:
            if rule.rule_type == "min":
                try:
                    min_val = float(rule.value)
                except (TypeError, ValueError):
                    pass
                break

        for rule in field.validation:
            rtype = rule.rule_type

            if rtype == "max_file_size":
                # Deferred to route handler
                continue

            if rtype == "required":
                if not value:
                    errors.append(_("{field}: This field is required.").format(field=_(field.label)))

            elif rtype == "min":
                if value:
                    try:
                        if float(value) < float(rule.value):
                            errors.append(
                                _("{field}: Value must be at least {value}.").format(
                                    field=_(field.label), value=rule.value
                                )
                            )
                    except (TypeError, ValueError):
                        errors.append(_("{field}: Must be a number.").format(field=_(field.label)))

            elif rtype == "max":
                if value:
                    try:
                        if float(value) > float(rule.value):
                            errors.append(
                                _("{field}: Value must be at most {value}.").format(
                                    field=_(field.label), value=rule.value
                                )
                            )
                    except (TypeError, ValueError):
                        errors.append(_("{field}: Must be a number.").format(field=_(field.label)))

            elif rtype == "step":
                if value:
                    try:
                        fval = float(value)
                        fstep = float(rule.value)
                        base = min_val if min_val is not None else 0.0
                        # Use a small tolerance to handle floating-point imprecision
                        remainder = abs((fval - base) % fstep)
                        tolerance = fstep * 1e-9
                        if remainder > tolerance and abs(remainder - fstep) > tolerance:
                            errors.append(
                                _("{field}: Value must be a multiple of {value}.").format(
                                    field=_(field.label), value=rule.value
                                )
                            )
                    except (TypeError, ValueError):
                        errors.append(_("{field}: Must be a number.").format(field=_(field.label)))

            elif rtype == "pattern":
                if value:
                    if not re.fullmatch(rule.value, value):
                        errors.append(
                            _("{field}: Value does not match the required format.").format(field=_(field.label))
                        )

            elif rtype == "one_of":
                if value not in rule.value:
                    allowed = ", ".join(str(v) for v in rule.value)
                    errors.append(
                        _("{field}: Must be one of: {allowed}.").format(field=_(field.label), allowed=allowed)
                    )

            elif rtype == "max_length":
                try:
                    if len(value) > int(rule.value):
                        errors.append(
                            _("{field}: Must be at most {value} characters.").format(
                                field=_(field.label), value=rule.value
                            )
                        )
                except (TypeError, ValueError):
                    pass

    return errors


def extract_field_values(
    form_data: dict[str, str | list[str]],
    fields: tuple[ConfigField, ...],
) -> dict[str, Any]:
    """
    Extract validated field values from form_data, keyed by config_key.

    Only fields whose config_key appears in the registry fields are extracted.
    Unknown form keys are silently dropped.
    Secret fields (is_secret=True) are excluded from the result.

    Type coercions:
    - boolean fields: present in form_data = True, absent = False
    - checkbox_group fields: collect all values into a list (form_data value
      may already be a list when the framework collects multi-value fields)
    - all other fields: string value as-is
    """
    result: dict[str, Any] = {}

    for field in fields:
        # Secret fields are never returned — handled separately by save_field_values
        if field.is_secret:
            continue

        key = field.config_key

        if field.field_type == "boolean":
            # Checkbox: present means True, absent means False
            result[key] = key in form_data
        elif field.field_type == "checkbox_group":
            # May be a list (multi-value) or a single string
            raw = form_data.get(key)
            if raw is None:
                result[key] = []
            elif isinstance(raw, list):
                result[key] = raw
            else:
                result[key] = [raw]
        else:
            if key in form_data:
                raw_val = form_data[key]
                # In case the framework handed us a list, take the first element
                result[key] = raw_val[0] if isinstance(raw_val, list) else raw_val

    return result


def save_field_values(
    values: dict[str, Any],
    section_def: SectionDef,
    config_dir: str,
) -> None:
    """
    Persist values to the correct backend, dispatching on config_target of the
    section's first field.

    Dispatch rules:
    - "stack.conf:<section>" → update_managed_region(Path(config_dir) / "stack.conf", section, values)
    - "api.conf:<section>"   → update_managed_region(Path(config_dir) / "api.conf", section, values)
    - "branding.json"        → update_branding(Path(config_dir), values)
    - "branding.json:<key>"  → update_branding(Path(config_dir), {key: values})
    - "pages.json"           → update_pages(Path(config_dir), hidden_pages_list)
    - "secrets.env"          → stub — logs a warning; full implementation deferred

    Raises ValueError for any config_target not matching the above patterns.
    """
    # Import registry here to avoid circular import at module level
    # (this module is loaded by registry/__init__.py which also imports registry)
    from .registry import registry as _registry

    fields = _registry.get_fields_for_section(section_def.section_id)
    if not fields:
        # Nothing to save
        return

    # Use the first field's config_target to determine the backend
    config_target = fields[0].config_target
    config_path = Path(config_dir)

    if config_target.startswith("stack.conf:"):
        section_name = config_target[len("stack.conf:"):]
        update_managed_region(config_path / "stack.conf", section_name, values)

    elif config_target.startswith("api.conf:"):
        section_name = config_target[len("api.conf:"):]
        update_managed_region(config_path / "api.conf", section_name, values)

    elif config_target == "branding.json":
        update_branding(config_path, values)

    elif config_target.startswith("branding.json:"):
        key = config_target[len("branding.json:"):]
        update_branding(config_path, {key: values})

    elif config_target == "pages.json":
        # values dict contains {"hidden_pages": [list of page slugs]}
        hidden: list[str] = values.get("hidden_pages", []) or []
        if not isinstance(hidden, list):
            hidden = [hidden]
        update_pages(config_path, hidden)

    elif config_target == "secrets.env":
        logger.warning(
            "save_field_values: secrets.env dispatch is not yet implemented "
            "(section=%s). Values were NOT saved.",
            section_def.section_id,
        )

    else:
        raise ValueError(
            f"Unknown config_target pattern {config_target!r} "
            f"for section {section_def.section_id!r}."
        )

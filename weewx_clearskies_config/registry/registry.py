"""
ConfigRegistry — central registry for all Clear Skies configurable sections,
fields, and wizard steps.

Built at import time via declarations.py.  All query methods return immutable
tuples.  Dict-based storage provides O(1) lookups by section_id and
step_number.

Module-level singleton:  `registry = ConfigRegistry()`
"""

from __future__ import annotations

from .fields import ConfigField
from .sections import SectionDef, WizardStepDef


class DuplicateSectionError(ValueError):
    """Raised when a section_id is registered more than once."""


class DuplicateStepError(ValueError):
    """Raised when a step_number is registered more than once."""


class ConfigRegistry:
    """
    Central registry for sections, fields, and wizard steps.

    Usage
    -----
    # at module level in declarations.py:
    from .registry import registry
    registry.register_section(section_def, fields)
    """

    def __init__(self) -> None:
        # section_id -> SectionDef (insertion order preserved in Python 3.7+)
        self._sections: dict[str, SectionDef] = {}
        # section_id -> tuple[ConfigField, ...]
        self._fields: dict[str, tuple[ConfigField, ...]] = {}
        # step_number -> WizardStepDef
        self._wizard_steps: dict[int, WizardStepDef] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_section(
        self,
        section: SectionDef,
        fields: tuple[ConfigField, ...],
    ) -> None:
        """
        Register a section with its fields.

        Raises DuplicateSectionError if section_id is already registered.
        """
        if section.section_id in self._sections:
            raise DuplicateSectionError(
                f"Section '{section.section_id}' is already registered."
            )
        self._sections[section.section_id] = section
        self._fields[section.section_id] = tuple(fields)

    def register_wizard_step(self, step: WizardStepDef) -> None:
        """
        Register a wizard step.

        Raises DuplicateStepError if step_number is already registered.
        """
        if step.step_number in self._wizard_steps:
            raise DuplicateStepError(
                f"Wizard step {step.step_number} is already registered."
            )
        self._wizard_steps[step.step_number] = step

    def register_card_config(
        self,
        card_type: str,
        fields: tuple[ConfigField, ...],
    ) -> None:
        """
        Register fields from a card manifest.

        Creates a SectionDef with section_id=f"card_{card_type}" in the
        "cards" domain group and registers it via register_section.
        """
        section = SectionDef(
            section_id=f"card_{card_type}",
            display_name=card_type.replace("_", " ").title(),
            domain_group="cards",
            config_source="",
        )
        self.register_section(section, fields)

    def load_card_config_fields(self, manifest_path: str) -> None:
        """Load configFields from card-manifest.json and register them.

        Reads the manifest, iterates cards with non-empty configFields,
        converts each to ConfigField objects, and registers under
        card_{card_type} sections in the 'cards' domain group.

        Silently returns if the manifest file doesn't exist or has no
        configFields (this is expected for v0.1 where no cards declare fields).
        """
        import json
        from pathlib import Path
        from .fields import ConfigField, FieldOption, ValidationRule

        path = Path(manifest_path)
        if not path.exists():
            return

        try:
            with open(path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        cards = manifest if isinstance(manifest, list) else manifest.get("cards", [])

        for card in cards:
            config_fields_data = card.get("configFields")
            if not config_fields_data:
                continue

            card_type = card.get("type", "unknown")
            section_id = f"card_{card_type}"

            fields = []
            for cf in config_fields_data:
                options = tuple(
                    FieldOption(value=o["value"], label=o["label"], description=o.get("description", ""))
                    for o in cf.get("options", [])
                )
                validation = tuple(
                    ValidationRule(rule_type=r["ruleType"], value=r["value"])
                    for r in cf.get("validation", [])
                )
                fields.append(ConfigField(
                    field_id=f"{section_id}.{cf['fieldId']}",
                    field_type=cf["fieldType"],
                    label=cf["label"],
                    help_text=cf.get("helpText", ""),
                    default=cf.get("default"),
                    options=options,
                    validation=validation,
                    config_target=f"stack.conf:card_{card_type}",
                    config_key=cf["fieldId"],
                ))

            if fields:
                self.register_card_config(card_type, tuple(fields))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_sections_for_group(
        self, domain_group: str
    ) -> tuple[SectionDef, ...]:
        """Return all sections in domain_group, in registration order."""
        return tuple(
            s for s in self._sections.values() if s.domain_group == domain_group
        )

    def get_fields_for_section(
        self, section_id: str
    ) -> tuple[ConfigField, ...]:
        """Return all fields for section_id, in registration order."""
        return self._fields.get(section_id, ())

    def get_wizard_steps(self) -> tuple[WizardStepDef, ...]:
        """Return all wizard steps sorted by step_number."""
        return tuple(
            self._wizard_steps[k] for k in sorted(self._wizard_steps)
        )

    def get_all_domain_groups(self) -> tuple[str, ...]:
        """
        Return all domain group names that have at least one registered
        section, in the order the first section of each group was registered.
        """
        seen: dict[str, None] = {}
        for section in self._sections.values():
            seen.setdefault(section.domain_group, None)
        return tuple(seen)


# Module-level singleton — populated by declarations.py at import time.
registry = ConfigRegistry()

"""
Frozen dataclasses for section and wizard-step grouping.

SectionDef groups fields for admin display.
WizardStepDef groups sections for the wizard's sequential flow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionDef:
    """
    Groups fields for admin display.

    domain_group must be one of:
        station, providers, appearance, dashboard, advanced, cards
    config_source identifies which file or API this section reads from
    (e.g. "stack.conf", "branding.json", "api.conf").
    """

    section_id: str
    display_name: str
    domain_group: str
    config_source: str
    custom_template: str = ""  # Path to escape-hatch template
    custom_handler: str = ""   # Dotted Python path to custom handler function


@dataclass(frozen=True)
class WizardStepDef:
    """
    Groups sections for the wizard's sequential flow.

    step_number controls the ordering of steps returned by
    ConfigRegistry.get_wizard_steps().
    """

    step_number: int
    title: str
    description: str
    section_ids: tuple[str, ...] = ()
    custom_template: str = ""  # Path to escape-hatch template

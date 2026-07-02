"""Unit-group options and presets for the Clear Skies setup wizard.

These definitions are shared by the unit-configuration wizard step (routes.py)
and the config writer (config_writer.py) to avoid duplication.
"""

from __future__ import annotations

from weewx_clearskies_config.i18n import get_current_locale, translate

# ---------------------------------------------------------------------------
# Valid options per unit group
# Each entry is (weewx_unit_string, human_label).
# ---------------------------------------------------------------------------

UNIT_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "group_temperature": [
        ("degree_F", "°F — Fahrenheit"),
        ("degree_C", "°C — Celsius"),
        ("degree_K", "K — Kelvin"),
    ],
    "group_speed": [
        ("mile_per_hour", "mph — Miles per hour"),
        ("km_per_hour", "km/h — Kilometers per hour"),
        ("knot", "knots — Knots"),
        ("meter_per_second", "m/s — Meters per second"),
    ],
    "group_pressure": [
        ("inHg", "inHg — Inches of mercury"),
        ("mbar", "mbar — Millibars"),
        ("hPa", "hPa — Hectopascals"),
        ("kPa", "kPa — Kilopascals"),
    ],
    "group_rain": [
        ("inch", "in — Inches"),
        ("cm", "cm — Centimeters"),
        ("mm", "mm — Millimeters"),
    ],
    "group_rainrate": [
        ("inch_per_hour", "in/h — Inches per hour"),
        ("cm_per_hour", "cm/h — Centimeters per hour"),
        ("mm_per_hour", "mm/h — Millimeters per hour"),
    ],
    "group_altitude": [
        ("foot", "ft — Feet"),
        ("meter", "m — Meters"),
    ],
    "group_distance": [
        ("mile", "mi — Miles"),
        ("km", "km — Kilometers"),
    ],
}

# Human-readable display name for each group (shown as the row label).
UNIT_GROUP_LABELS: dict[str, str] = {
    "group_temperature": "Temperature",
    "group_speed": "Wind Speed",
    "group_pressure": "Pressure",
    "group_rain": "Precipitation",
    "group_rainrate": "Precipitation Rate",
    "group_altitude": "Altitude",
    "group_distance": "Distance",
}

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

UNIT_PRESETS: dict[str, dict[str, str]] = {
    "us": {
        "group_temperature": "degree_F",
        "group_speed": "mile_per_hour",
        "group_pressure": "inHg",
        "group_rain": "inch",
        "group_rainrate": "inch_per_hour",
        "group_altitude": "foot",
        "group_distance": "mile",
    },
    "metric": {
        "group_temperature": "degree_C",
        "group_speed": "km_per_hour",
        "group_pressure": "mbar",
        "group_rain": "cm",
        "group_rainrate": "cm_per_hour",
        "group_altitude": "meter",
        "group_distance": "km",
    },
    "metricwx": {
        "group_temperature": "degree_C",
        "group_speed": "meter_per_second",
        "group_pressure": "mbar",
        "group_rain": "mm",
        "group_rainrate": "mm_per_hour",
        "group_altitude": "meter",
        "group_distance": "km",
    },
}

# Flat set of all valid unit strings across all groups — used for validation.
_ALL_VALID_UNITS: frozenset[str] = frozenset(
    unit for options in UNIT_OPTIONS.values() for unit, _ in options
)


def validate_units(units: dict[str, str]) -> dict[str, str]:
    """Validate a unit-group dict submitted from the wizard step.

    Returns a dict of {group_name: error_message} for each invalid entry.
    An empty dict means the submission is valid.
    """
    locale = get_current_locale()
    errors: dict[str, str] = {}
    for group, options in UNIT_OPTIONS.items():
        valid_units = {u for u, _ in options}
        submitted = units.get(group, "")
        if not submitted:
            errors[group] = translate("A unit must be selected for {group}.", locale).format(
                group=UNIT_GROUP_LABELS.get(group, group)
            )
        elif submitted not in valid_units:
            errors[group] = translate(
                '"{submitted}" is not a valid unit for {group}.', locale
            ).format(submitted=submitted, group=UNIT_GROUP_LABELS.get(group, group))
    return errors

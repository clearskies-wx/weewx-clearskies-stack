"""skin.conf import parser for the Clear Skies setup wizard (ADR-043).

Parses a weewx skin.conf file (ConfigObj INI format) and extracts configuration
that maps to Clear Skies settings. Used by the setup wizard to pre-populate all
configuration steps when an operator migrates from an existing skin.
"""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class SkinImportError(Exception):
    """Raised when skin.conf cannot be parsed."""


# ---------------------------------------------------------------------------
# Sections to silently skip (Cheetah / weewx-engine internals)
# ---------------------------------------------------------------------------

_SILENT_SKIP_SECTIONS: frozenset[str] = frozenset(
    {
        "Generators",
        "CheetahGenerator",
        "ImageGenerator",
        "CopyGenerator",
        "StdReport",
    }
)


def _is_silently_skipped(section_name: str) -> bool:
    """Return True if *section_name* should be skipped without a warning."""
    return section_name in _SILENT_SKIP_SECTIONS or section_name.startswith("Std")


# ---------------------------------------------------------------------------
# [Extras] key-categorisation patterns
# Matching order: branding → social → mqtt → providers → pwa → theme → feature_toggles.
# social _enabled keys must match social before feature_toggles gets a chance.
# ---------------------------------------------------------------------------

_EXTRAS_PATTERNS: dict[str, dict[str, set[str]]] = {
    "branding": {
        "exact": {"site_title", "logo_image", "logo_image_dark", "favicon"},
    },
    "social": {
        "exact": {
            "facebook_enabled",
            "twitter_enabled",
            "social_share_html",
            "instagram_enabled",
            "youtube_enabled",
        },
        "prefix": {"facebook_", "twitter_", "instagram_", "youtube_"},
    },
    "mqtt": {
        "prefix": {"mqtt_websockets_"},
    },
    "providers": {
        "exact": {"forecast_provider", "earthquake_maxradiuskm"},
        "suffix": {"_api_id", "_api_secret", "_api_key"},
        "prefix": {"forecast_", "aqi_", "earthquake_", "radar_"},
    },
    "pwa": {
        "prefix": {"manifest_"},
    },
    "theme": {
        "exact": {"theme", "theme_toggle_enabled"},
    },
    "feature_toggles": {
        # Catches remaining *_enabled keys not already claimed by social.
        "suffix": {"_enabled"},
    },
}

# Ordered list preserves matching priority (dict is ordered in Python 3.7+).
_EXTRAS_CATEGORY_ORDER: list[str] = list(_EXTRAS_PATTERNS.keys())


def _categorize_extras_key(key: str) -> str | None:
    """Return the category name for *key*, or None if no pattern matches.

    Prefix matching for the 'providers' category is intentionally skipped when
    the key ends with '_enabled'.  Keys like 'radar_enabled' or
    'earthquake_enabled' are feature toggles even though their prefix matches
    a provider namespace ('radar_', 'earthquake_').  The feature_toggles
    category is the correct home for *_enabled toggles that aren't in social.
    """
    for category in _EXTRAS_CATEGORY_ORDER:
        patterns = _EXTRAS_PATTERNS[category]
        if key in patterns.get("exact", set()):
            return category
        for pfx in patterns.get("prefix", set()):
            if key.startswith(pfx):
                # Don't let provider-prefix patterns claim *_enabled keys —
                # those belong in feature_toggles (unless social claimed them).
                if category == "providers" and key.endswith("_enabled"):
                    continue
                return category
        if any(key.endswith(sfx) for sfx in patterns.get("suffix", set())):
            return category
    return None


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_units(units_section: Any) -> dict[str, Any]:
    """Extract all [Units] subsections into a structured dict."""
    result: dict[str, Any] = {
        "groups": {},
        "labels": {},
        "string_formats": {},
        "ordinates": {"directions": [], "na": "N/A"},
        "time_formats": {},
        "degree_days": {},
        "trend": {},
        "timezone": None,
    }

    # [[Groups]]
    groups = units_section.get("Groups", {})
    if groups:
        result["groups"] = dict(groups)
        logger.debug("Extracted %d unit groups from [Units][[Groups]]", len(result["groups"]))

    # [[Labels]]
    labels_raw = units_section.get("Labels", {})
    if labels_raw:
        labels: dict[str, str] = {}
        for k, v in labels_raw.items():
            # ConfigObj can return a list for plural/singular forms; join to string.
            labels[k] = ", ".join(v) if isinstance(v, list) else str(v)
        result["labels"] = labels
        logger.debug("Extracted %d unit labels from [Units][[Labels]]", len(labels))

    # [[StringFormats]]
    string_formats = units_section.get("StringFormats", {})
    if string_formats:
        result["string_formats"] = dict(string_formats)
        logger.debug(
            "Extracted %d string formats from [Units][[StringFormats]]",
            len(result["string_formats"]),
        )

    # [[Ordinates]]
    ordinates_raw = units_section.get("Ordinates", {})
    if ordinates_raw:
        directions_raw = ordinates_raw.get("directions", "")
        if isinstance(directions_raw, list):
            directions = [d.strip() for d in directions_raw]
        else:
            directions = [d.strip() for d in str(directions_raw).split(",") if d.strip()]
        na_val = ordinates_raw.get("N/A", ordinates_raw.get("na", "N/A"))
        result["ordinates"] = {"directions": directions, "na": str(na_val)}
        logger.debug("Extracted %d compass directions from [Units][[Ordinates]]", len(directions))

    # [[TimeFormats]]
    time_formats = units_section.get("TimeFormats", {})
    if time_formats:
        result["time_formats"] = dict(time_formats)
        logger.debug(
            "Extracted %d time formats from [Units][[TimeFormats]]",
            len(result["time_formats"]),
        )

    # [[DegreeDays]] — keep values as strings ("65, degree_F").
    # ConfigObj may parse "65, degree_F" as a list ['65', 'degree_F']; re-join.
    degree_days_raw = units_section.get("DegreeDays", {})
    if degree_days_raw:
        degree_days: dict[str, str] = {}
        for k, v in degree_days_raw.items():
            degree_days[k] = ", ".join(v) if isinstance(v, list) else str(v)
        result["degree_days"] = degree_days
        logger.debug("Extracted degree-days config from [Units][[DegreeDays]]")

    # [[Trend]] — time_delta and time_grace are integers (seconds)
    trend_raw = units_section.get("Trend", {})
    if trend_raw:
        trend: dict[str, Any] = {}
        for k, v in trend_raw.items():
            if k in ("time_delta", "time_grace"):
                try:
                    trend[k] = int(v)
                except (ValueError, TypeError):
                    trend[k] = v
                    logger.warning(
                        "[Units][[Trend]] key %r could not be converted to int: %r", k, v
                    )
            else:
                trend[k] = v
        result["trend"] = trend
        logger.debug("Extracted trend config from [Units][[Trend]]")

    # [[TimeZone]]
    tz_section = units_section.get("TimeZone", {})
    if tz_section:
        # weewx stores a single string value here
        tz_val = tz_section.get("timezone") or tz_section.get("zone")
        if tz_val:
            result["timezone"] = str(tz_val)

    return result


def _parse_labels_generic(labels_section: Any) -> dict[str, str]:
    """Extract [Labels][[Generic]] key-value pairs."""
    generic = labels_section.get("Generic", {})
    if not generic:
        return {}
    result = dict(generic)
    logger.debug("Extracted %d observation labels from [Labels][[Generic]]", len(result))
    return result


def _parse_extras(extras_section: Any) -> tuple[dict[str, Any], list[str]]:
    """Categorise [Extras] keys and return (extras_dict, warnings)."""
    extras: dict[str, Any] = {
        "branding": {},
        "social": {},
        "mqtt": {},
        "providers": {},
        "feature_toggles": {},
        "pwa": {},
        "theme": {},
        "unmatched": {},
    }
    warnings: list[str] = []

    for key, value in extras_section.items():
        # Skip sub-sections (ConfigObj sub-sections are dicts)
        if hasattr(value, "items"):
            continue
        category = _categorize_extras_key(key)
        if category is not None:
            extras[category][key] = value
        else:
            extras["unmatched"][key] = value
            msg = f"[Extras] key {key!r} does not match any known pattern — stored in extras.unmatched"
            warnings.append(msg)
            logger.warning(msg)

    return extras, warnings


def _parse_almanac(almanac_section: Any) -> dict[str, Any]:
    """Extract [Almanac] moon_phases list."""
    raw = almanac_section.get("moon_phases", "")
    if isinstance(raw, list):
        phases = [p.strip() for p in raw if p.strip()]
    else:
        phases = [p.strip() for p in str(raw).split(",") if p.strip()]
    logger.debug("Extracted %d moon phase labels from [Almanac]", len(phases))
    return {"moon_phases": phases}


def _parse_texts(texts_section: Any) -> dict[str, str]:
    """Extract [Texts] as a flat string dict."""
    result: dict[str, str] = {}
    for key, value in texts_section.items():
        if not hasattr(value, "items"):
            result[key] = str(value)
    return result


# ---------------------------------------------------------------------------
# Core parsing logic (works on a ConfigObj mapping)
# ---------------------------------------------------------------------------


def _extract(conf: Any) -> dict[str, Any]:
    """Walk *conf* (a ConfigObj-parsed mapping) and extract Clear Skies config."""
    import configobj  # local import keeps top-level import list short

    warnings: list[str] = []

    result: dict[str, Any] = {
        "units": {
            "groups": {},
            "labels": {},
            "string_formats": {},
            "ordinates": {"directions": [], "na": "N/A"},
            "time_formats": {},
            "degree_days": {},
            "trend": {},
            "timezone": None,
        },
        "labels": {},
        "extras": {
            "branding": {},
            "social": {},
            "mqtt": {},
            "providers": {},
            "feature_toggles": {},
            "pwa": {},
            "theme": {},
            "unmatched": {},
        },
        "almanac": {"moon_phases": []},
        "texts": {},
        "warnings": [],
    }

    for section_name, section_value in conf.items():
        if not isinstance(section_value, configobj.Section):
            # Top-level scalar — skip (not expected in skin.conf)
            continue

        if _is_silently_skipped(section_name):
            logger.info("Skipping Cheetah-specific section [%s]", section_name)
            continue

        if section_name == "Units":
            result["units"] = _parse_units(section_value)

        elif section_name == "Labels":
            result["labels"] = _parse_labels_generic(section_value)

        elif section_name == "Extras":
            extras, extra_warnings = _parse_extras(section_value)
            result["extras"] = extras
            warnings.extend(extra_warnings)

        elif section_name == "Almanac":
            result["almanac"] = _parse_almanac(section_value)

        elif section_name == "Texts":
            result["texts"] = _parse_texts(section_value)

        else:
            logger.debug("Skipping unrecognised top-level section [%s]", section_name)

    result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_skin_conf(path: str) -> dict[str, Any]:
    """Parse a weewx skin.conf and return structured config for wizard pre-fill.

    Args:
        path: Filesystem path to a skin.conf file.

    Returns:
        Dict with keys: units, labels, extras, almanac, texts, warnings.

    Raises:
        FileNotFoundError: If path doesn't exist.
        SkinImportError: If file is not valid ConfigObj format.
    """
    import configobj

    try:
        conf = configobj.ConfigObj(path, encoding="utf-8", file_error=True)
    except OSError as exc:
        # configobj raises OSError (or its subclass) for missing files
        raise FileNotFoundError(f"skin.conf not found: {path}") from exc
    except configobj.ParseError as exc:
        raise SkinImportError(f"skin.conf parse error: {exc}") from exc
    except Exception as exc:
        raise SkinImportError(f"Failed to parse skin.conf: {exc}") from exc

    return _extract(conf)


def parse_skin_conf_text(text: str) -> dict[str, Any]:
    """Parse raw skin.conf text content and return structured config for wizard pre-fill.

    Accepts raw text (e.g. from a file upload) rather than a filesystem path.

    Args:
        text: Raw skin.conf file content as a string.

    Returns:
        Dict with keys: units, labels, extras, almanac, texts, warnings.

    Raises:
        SkinImportError: If the text is not valid ConfigObj format.
    """
    import configobj

    try:
        conf = configobj.ConfigObj(io.StringIO(text), encoding="utf-8")
    except configobj.ParseError as exc:
        raise SkinImportError(f"skin.conf parse error: {exc}") from exc
    except Exception as exc:
        raise SkinImportError(f"Failed to parse skin.conf text: {exc}") from exc

    return _extract(conf)

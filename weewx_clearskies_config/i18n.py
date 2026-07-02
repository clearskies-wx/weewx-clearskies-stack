"""Wizard/admin internationalization — Jinja2 integration with JSON locale files.

Two independent locale concepts exist in this codebase; do not conflate them:

- **Wizard UI locale** (this module): what language the *operator* sees while
  running the setup wizard / admin UI.  Chosen once via the language step,
  stored in the ``clearskies-wizard-locale`` cookie, and applied per-request
  via a ``contextvars.ContextVar`` so the Jinja2 ``_()`` global can look up
  strings without every route threading a ``locale`` parameter through.
- **Dashboard default locale** (``state.default_locale`` in
  ``wizard/routes.py``, ADR-021): what language *dashboard visitors* see by
  default. That value is written to the generated site config, not read from
  here.
"""

from __future__ import annotations

import contextvars
import json
from pathlib import Path

from markupsafe import Markup

#: Cookie that persists the operator's chosen wizard UI language across
#: requests. 1 year max-age; see ``wizard/routes.py:wizard_set_language``.
LOCALE_COOKIE_NAME = "clearskies-wizard-locale"

#: Locale used when no cookie is set, no Accept-Language match is found, or a
#: requested key/locale is missing.
DEFAULT_LOCALE = "en"

_translations: dict[str, dict[str, str]] = {}

# Per-request current locale. Set by the locale middleware in app.py before
# the route handler (and therefore template rendering) runs; read by the
# Jinja2 `_()` global registered on the templates environment.
_current_locale: contextvars.ContextVar[str] = contextvars.ContextVar(
    "wizard_locale", default=DEFAULT_LOCALE
)


def load_translations(translations_dir: Path | None = None) -> None:
    """Load all translation JSON files into memory.

    Call once at application startup, before any request is served. Safe to
    call again (e.g. in tests) — it simply repopulates ``_translations``.
    """
    if translations_dir is None:
        translations_dir = Path(__file__).parent / "translations"
    for path in sorted(translations_dir.glob("*.json")):
        locale_code = path.stem
        with open(path, encoding="utf-8") as f:
            _translations[locale_code] = json.load(f)


def translate(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Look up a translation by key. Falls back to English, then the key itself.

    Returns a ``markupsafe.Markup`` instance (a ``str`` subclass) so that
    Jinja2's autoescape does not re-escape translated values that legitimately
    contain HTML (e.g. ``<sub>``, ``<code>``, ``<strong>``). The translation
    content comes from our own trusted JSON files under ``translations/``,
    never from user input, so marking it safe here is correct — see
    I18N-COMPLIANCE-PLAN.md "Jinja2 autoescape double-escaping" note.
    """
    value = _translations.get(locale, {}).get(key)
    if value:
        return Markup(value)
    if locale != DEFAULT_LOCALE:
        value = _translations.get(DEFAULT_LOCALE, {}).get(key)
        if value:
            return Markup(value)
    return Markup(key)


def get_current_locale() -> str:
    """Return the wizard UI locale for the request currently being handled."""
    return _current_locale.get()


def set_current_locale(locale: str) -> contextvars.Token[str]:
    """Set the wizard UI locale for the request currently being handled.

    Returns the token needed to reset the contextvar afterwards (see the
    locale middleware in ``app.py``, which resets it once the response has
    been produced so the value never leaks into an unrelated request).
    """
    return _current_locale.set(locale)


def reset_current_locale(token: contextvars.Token[str]) -> None:
    """Undo a prior ``set_current_locale`` call. See that function's docstring."""
    _current_locale.reset(token)


def get_supported_locales() -> list[dict[str, str]]:
    """Return the 13 supported wizard UI locales with native-script labels."""
    return [
        {"code": "en", "name": "English", "native": "English"},
        {"code": "de", "name": "German", "native": "Deutsch"},
        {"code": "es", "name": "Spanish", "native": "Español"},
        {"code": "fil", "name": "Filipino", "native": "Filipino"},
        {"code": "fr", "name": "French", "native": "Français"},
        {"code": "it", "name": "Italian", "native": "Italiano"},
        {"code": "ja", "name": "Japanese", "native": "日本語"},
        {"code": "nl", "name": "Dutch", "native": "Nederlands"},
        {"code": "pt-BR", "name": "Portuguese (Brazil)", "native": "Português (Brasil)"},
        {"code": "pt-PT", "name": "Portuguese (Portugal)", "native": "Português (Portugal)"},
        {"code": "ru", "name": "Russian", "native": "Русский"},
        {"code": "zh-CN", "name": "Chinese (Simplified)", "native": "简体中文"},
        {"code": "zh-TW", "name": "Chinese (Traditional)", "native": "繁體中文"},
    ]

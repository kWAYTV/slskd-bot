"""Locale lookup. English is the source; other locales fall back to it."""

from __future__ import annotations

from slskd_importer.telegram.i18n.de import STRINGS as DE
from slskd_importer.telegram.i18n.en import STRINGS as EN
from slskd_importer.telegram.i18n.es import STRINGS as ES
from slskd_importer.telegram.i18n.gl import STRINGS as GL

DEFAULT_LOCALE = "en"

LABELS = {
    "en": "English",
    "es": "Español",
    "gl": "Galego",
    "de": "Deutsch",
}

LOCALES = tuple(LABELS)

CATALOGS: dict[str, dict[str, str]] = {
    "en": EN,
    "es": ES,
    "gl": GL,
    "de": DE,
}


def normalize_locale(code: str | None) -> str:
    """Map a Telegram ``language_code`` (or stored value) onto a supported locale."""
    if not isinstance(code, str) or not code:
        return DEFAULT_LOCALE
    base = code.split("-", 1)[0].lower()
    return base if base in CATALOGS else DEFAULT_LOCALE


def t(locale: str, key: str, **kwargs: object) -> str:
    """Translate ``key`` for ``locale``, falling back to English."""
    catalog = CATALOGS.get(normalize_locale(locale), EN)
    text = catalog.get(key) or EN[key]
    if kwargs:
        return text.format(**kwargs)
    return text

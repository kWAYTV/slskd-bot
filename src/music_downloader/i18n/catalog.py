"""GNU gettext catalogs with a per-task locale (safe for concurrent users).

python-telegram-bot has no built-in i18n. The library maintainers point at
gettext or a settings menu; Python's own docs plus Babel 2.17 are the current
catalog toolchain. Never call ``gettext.install()`` in an async bot — one
process serves many locales at once, so locale lives in a ContextVar.
"""

from __future__ import annotations

import gettext as gettextlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.resources import files
from pathlib import Path

DOMAIN = "messages"
DEFAULT_LOCALE = "en"

# Native endonyms — shown on the picker so users can choose before a locale exists.
SUPPORTED_LOCALES: dict[str, str] = {
    "en": "English",
    "es": "Español",
    "de": "Deutsch",
    "gl": "Galego",
}

_current_locale: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)
_catalogs: dict[str, gettextlib.NullTranslations] | None = None


def locales_dir() -> Path:
    return Path(str(files("music_downloader").joinpath("locales")))


def _load_catalogs() -> dict[str, gettextlib.NullTranslations]:
    directory = str(locales_dir())
    loaded: dict[str, gettextlib.NullTranslations] = {
        DEFAULT_LOCALE: gettextlib.NullTranslations(),
    }
    for locale in SUPPORTED_LOCALES:
        if locale == DEFAULT_LOCALE:
            continue
        loaded[locale] = gettextlib.translation(
            DOMAIN,
            localedir=directory,
            languages=[locale],
            fallback=True,
        )
    return loaded


def _translations() -> dict[str, gettextlib.NullTranslations]:
    global _catalogs
    if _catalogs is None:
        _catalogs = _load_catalogs()
    return _catalogs


def current_locale() -> str:
    return _current_locale.get()


def set_locale(locale: str) -> str:
    """Activate ``locale`` for the current asyncio task. Returns the resolved code."""
    resolved = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    _current_locale.set(resolved)
    return resolved


def negotiate_locale(language_code: str | None) -> str:
    """Map Telegram ``User.language_code`` (e.g. ``es-ES``) onto a supported locale."""
    if not language_code:
        return DEFAULT_LOCALE
    normalized = language_code.replace("_", "-").lower()
    if normalized in SUPPORTED_LOCALES:
        return normalized
    base = normalized.split("-", 1)[0]
    if base in SUPPORTED_LOCALES:
        return base
    return DEFAULT_LOCALE


@contextmanager
def use_locale(locale: str) -> Iterator[str]:
    token = _current_locale.set(set_locale(locale))
    try:
        yield current_locale()
    finally:
        _current_locale.reset(token)


def gettext(message: str) -> str:
    return _translations()[current_locale()].gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translations()[current_locale()].ngettext(singular, plural, n)


_ = gettext

"""User-facing translations via GNU gettext (async-safe, per-user locale)."""

from music_downloader.i18n.catalog import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    current_locale,
    gettext,
    negotiate_locale,
    ngettext,
    set_locale,
    use_locale,
)
from music_downloader.i18n.store import LocaleStore

__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "LocaleStore",
    "current_locale",
    "gettext",
    "negotiate_locale",
    "ngettext",
    "set_locale",
    "use_locale",
]

from slskd_importer.telegram.i18n import DEFAULT_LOCALE, LABELS, LOCALES, normalize_locale, t
from slskd_importer.telegram.i18n.catalog import CATALOGS


class TestCatalog:
    def test_supported_locales(self):
        assert LOCALES == ("en", "es", "gl", "de")
        assert DEFAULT_LOCALE == "en"
        assert set(LABELS) == set(LOCALES) == set(CATALOGS)

    def test_keys_match_english(self):
        english = set(CATALOGS["en"])
        for locale, catalog in CATALOGS.items():
            assert set(catalog) == english, locale

    def test_english_is_default_and_fallback(self):
        assert t("en", "lang_pick") == "Choose your language:"
        assert t("zz", "lang_pick") == "Choose your language:"
        assert t("es", "lang_pick") == "Elige tu idioma:"
        assert t("gl", "lang_pick") == "Escolle o teu idioma:"
        assert t("de", "lang_pick") == "Wähle deine Sprache:"

    def test_format_kwargs(self):
        assert t("en", "lang_set", language="Español") == "Language set to *Español*."
        assert "Español" in t("es", "lang_set", language="Español")

    def test_normalize_locale(self):
        assert normalize_locale(None) == "en"
        assert normalize_locale("es-ES") == "es"
        assert normalize_locale("de") == "de"
        assert normalize_locale("pt-BR") == "en"
        assert normalize_locale(object()) == "en"  # type: ignore[arg-type]

from __future__ import annotations

import pytest

from slskd_importer.records.database import Database
from slskd_importer.records.prefs import ChatPrefsRepository


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    yield ChatPrefsRepository(db)
    db.close()


class TestChatPrefsRepository:
    def test_get_missing_returns_none(self, repo):
        assert repo.get_locale(123) is None

    def test_set_and_get_locale(self, repo):
        repo.set_locale(123, "es")
        assert repo.get_locale(123) == "es"

    def test_locale_upsert(self, repo):
        repo.set_locale(123, "es")
        repo.set_locale(123, "de")
        assert repo.get_locale(123) == "de"

    def test_load_all_locales(self, repo):
        repo.set_locale(1, "es")
        repo.set_locale(2, "gl")
        assert repo.load_all_locales() == {1: "es", 2: "gl"}

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
        assert repo.get_quality(123) is None

    def test_set_and_get(self, repo):
        repo.set_quality(123, "cd")
        assert repo.get_quality(123) == "cd"

    def test_upsert(self, repo):
        repo.set_quality(123, "cd")
        repo.set_quality(123, "hires")
        assert repo.get_quality(123) == "hires"

    def test_load_all_quality(self, repo):
        repo.set_quality(1, "cd")
        repo.set_quality(2, "hires")
        assert repo.load_all_quality() == {1: "cd", 2: "hires"}

    def test_set_locale_does_not_clobber_quality(self, repo):
        repo.set_quality(123, "cd")
        repo.set_locale(123, "es")
        assert repo.get_quality(123) == "cd"
        assert repo.get_locale(123) == "es"

    def test_set_locale_alone_leaves_quality_unset(self, repo):
        repo.set_locale(5, "de")
        assert repo.get_quality(5) is None
        assert repo.get_locale(5) == "de"
        assert repo.load_all_quality() == {}
        assert repo.load_all_locales() == {5: "de"}

    def test_load_all_locales(self, repo):
        repo.set_locale(1, "es")
        repo.set_locale(2, "gl")
        assert repo.load_all_locales() == {1: "es", 2: "gl"}

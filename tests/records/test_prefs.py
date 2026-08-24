from __future__ import annotations

import pytest

from music_downloader.records.database import Database
from music_downloader.records.prefs import ChatPrefsRepository


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

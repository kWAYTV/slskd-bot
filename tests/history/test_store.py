from __future__ import annotations

import pytest

from slskd_importer.history.store import HistoryRepository
from slskd_importer.records.database import Database


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    yield HistoryRepository(db)
    db.close()


class TestAdd:
    def test_add_returns_row_id(self, repo):
        row_id = repo.add(
            artist="Artist1",
            title="Title1",
            filename="file.flac",
            source_user="user1",
            status="completed",
        )
        assert row_id == 1

    def test_add_record_appears_in_get_recent(self, repo):
        repo.add(
            artist="Artist1",
            title="Title1",
            filename="file.flac",
            source_user="user1",
            status="completed",
            album="Album1",
            remote_path="/remote/path",
            duration_secs=240,
            file_size=10_000_000,
        )
        records = repo.get_recent()
        assert len(records) == 1
        rec = records[0]
        assert rec.artist == "Artist1"
        assert rec.title == "Title1"
        assert rec.album == "Album1"
        assert rec.filename == "file.flac"
        assert rec.source_user == "user1"
        assert rec.remote_path == "/remote/path"
        assert rec.status == "completed"
        assert rec.duration_secs == 240
        assert rec.file_size == 10_000_000
        assert rec.chat_id is None
        assert rec.spotify_url == ""


class TestGetRecent:
    def test_descending_chronological_order(self, repo):
        repo.add(artist="First", title="T1", filename="f1", source_user="u", status="ok")
        # SQLite datetime('now') has second precision; insert a manual delay isn't reliable,
        # so we insert with distinct created_at via raw SQL isn't possible through the repo.
        # Instead, add multiple and check order by id (autoincrement matches insert order
        # when created_at is the same second, ORDER BY created_at DESC, id DESC implicitly).
        repo.add(artist="Second", title="T2", filename="f2", source_user="u", status="ok")
        repo.add(artist="Third", title="T3", filename="f3", source_user="u", status="ok")
        records = repo.get_recent()
        artists = [r.artist for r in records]
        # Most recent first (DESC by created_at — all same second, but rowid order is preserved
        # since SQLite returns ties in insertion order for DESC when using AUTOINCREMENT).
        assert artists == ["Third", "Second", "First"]

    def test_respects_limit(self, repo):
        for i in range(10):
            repo.add(artist=f"A{i}", title=f"T{i}", filename=f"f{i}", source_user="u", status="ok")
        records = repo.get_recent(limit=3)
        assert len(records) == 3

    def test_empty_database_returns_empty_list(self, repo):
        records = repo.get_recent()
        assert records == []


class TestCount:
    def test_count_after_multiple_adds(self, repo):
        assert repo.count() == 0
        repo.add(artist="A1", title="T1", filename="f1", source_user="u", status="ok")
        assert repo.count() == 1
        repo.add(artist="A2", title="T2", filename="f2", source_user="u", status="ok")
        assert repo.count() == 2
        repo.add(artist="A3", title="T3", filename="f3", source_user="u", status="ok")
        assert repo.count() == 3

    def test_count_empty_database(self, repo):
        assert repo.count() == 0


class TestChatScopedHistory:
    def test_get_recent_filters_chat_id(self, repo):
        repo.add(artist="A", title="T1", filename="f1", source_user="u", status="success", chat_id=10)
        repo.add(artist="B", title="T2", filename="f2", source_user="u", status="success", chat_id=20)
        records = repo.get_recent(chat_id=10)
        assert len(records) == 1
        assert records[0].filename == "f1"

    def test_count_filters_chat_id(self, repo):
        repo.add(artist="A", title="T1", filename="f1", source_user="u", status="success", chat_id=10)
        repo.add(artist="B", title="T2", filename="f2", source_user="u", status="success", chat_id=20)
        assert repo.count(chat_id=10) == 1
        assert repo.count() == 2


class TestFindSuccess:
    def test_finds_by_artist_title(self, repo):
        repo.add(artist="Artist", title="Song", filename="a.flac", source_user="u", status="failed")
        repo.add(artist="Artist", title="Song", filename="b.flac", source_user="u", status="success")
        hit = repo.find_success("artist", "song")
        assert hit is not None
        assert hit.filename == "b.flac"

    def test_finds_by_spotify_url(self, repo):
        repo.add(
            artist="Other",
            title="Name",
            filename="x.flac",
            source_user="u",
            status="success",
            spotify_url="https://open.spotify.com/track/abc",
        )
        hit = repo.find_success("ignored", "ignored", spotify_url="https://open.spotify.com/track/abc")
        assert hit is not None
        assert hit.filename == "x.flac"

    def test_url_falls_back_to_artist_title_for_legacy_rows(self, repo):
        # Row written before the spotify_url column existed (empty URL)
        repo.add(artist="Artist", title="Song", filename="legacy.flac", source_user="u", status="success")
        hit = repo.find_success("Artist", "Song", spotify_url="https://open.spotify.com/track/new")
        assert hit is not None
        assert hit.filename == "legacy.flac"

    def test_returns_none_when_missing(self, repo):
        assert repo.find_success("Nope", "Missing") is None


class TestUndoSupport:
    def test_get_last_saved_returns_latest_success(self, repo):
        repo.add(artist="A", title="One", filename="A - One.flac", source_user="u", status="success", chat_id=5)
        repo.add(artist="B", title="Two", filename="B - Two.flac", source_user="u", status="success", chat_id=5)
        repo.add(artist="C", title="Three", filename="C - Three.flac", source_user="u", status="rejected", chat_id=5)
        entry = repo.get_last_saved(5)
        assert entry is not None
        assert entry.filename == "B - Two.flac"

    def test_get_last_saved_scoped_to_chat(self, repo):
        repo.add(artist="A", title="One", filename="A - One.flac", source_user="u", status="success", chat_id=5)
        assert repo.get_last_saved(99) is None

    def test_set_status_marks_undone(self, repo):
        row_id = repo.add(
            artist="A", title="One", filename="A - One.flac", source_user="u", status="success", chat_id=5
        )
        repo.set_status(row_id, "undone")
        assert repo.get_last_saved(5) is None
        assert repo.get_recent(1, 5)[0].status == "undone"

    def test_get_for_chat_scopes_to_owner(self, repo):
        row_id = repo.add(
            artist="A", title="One", filename="A - One.flac", source_user="u", status="success", chat_id=5
        )
        assert repo.get_for_chat(row_id, 5) is not None
        assert repo.get_for_chat(row_id, 99) is None


class TestSummarize:
    def test_empty_chat(self, repo):
        stats = repo.summarize(5)
        assert stats.total == 0
        assert stats.success == 0
        assert stats.top_sources == []

    def test_counts_and_top_sources(self, repo):
        repo.add(artist="A", title="1", filename="a.flac", source_user="alice", status="success", chat_id=5)
        repo.add(artist="B", title="2", filename="b.flac", source_user="alice", status="success", chat_id=5)
        repo.add(artist="C", title="3", filename="c.flac", source_user="bob", status="failed", chat_id=5)
        repo.add(artist="D", title="4", filename="d.flac", source_user="carol", status="success", chat_id=99)
        stats = repo.summarize(5)
        assert stats.total == 3
        assert stats.success == 2
        assert stats.failed == 1
        assert stats.top_sources == [("alice", 2)]

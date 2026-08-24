"""Tests for the shared SQLite database: creation, recovery, migration."""

import os
import tempfile

from slskd_importer.records.database import Database


class TestDatabaseNormalCreation:
    """Test normal database creation and schema."""

    def test_database_normal_creation(self, tmp_path):
        """Create DB in a temp dir, verify tables exist."""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)

        cursor = db.connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        assert "download_history" in tables
        assert "import_jobs" in tables
        assert "import_tracks" in tables
        assert "chat_prefs" in tables
        db.close()

    def test_database_schema_version(self, tmp_path):
        """Verify user_version is set to 4."""
        db_path = str(tmp_path / "version.db")
        db = Database(db_path)

        cursor = db.connection.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]
        assert version == 4
        db.close()


class TestDatabaseCorruptRecovery:
    """Test corrupt database recovery (lines 76-85)."""

    def test_database_corrupt_file_recreated(self, tmp_path):
        """Write garbage to a file, then create Database with that path - should recreate."""
        db_path = str(tmp_path / "corrupt.db")

        # Write garbage that looks like a sqlite header but is corrupt
        with open(db_path, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 200)

        db = Database(db_path)

        # Should have recreated cleanly with valid schema
        cursor = db.connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        assert "download_history" in tables
        assert "import_jobs" in tables
        assert "import_tracks" in tables
        backups = list(tmp_path.glob("corrupt.db.bak.*"))
        assert len(backups) == 1
        db.close()

    def test_database_corrupt_nonexistent_parent(self):
        """Corrupt recovery with nested parent dirs that don't exist yet."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "deep", "nested", "corrupt.db")

            # Create the path so we can write garbage
            os.makedirs(os.path.dirname(db_path))
            with open(db_path, "wb") as f:
                f.write(b"SQLite format 3\x00" + b"\xde\xad" * 100)

            db = Database(db_path)
            cursor = db.connection.execute("PRAGMA user_version")
            assert cursor.fetchone()[0] == 4
            db.close()


class TestDatabaseMigration:
    def test_adds_history_columns_to_legacy_schema(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT DEFAULT '',
                filename TEXT NOT NULL,
                source_user TEXT NOT NULL,
                remote_path TEXT DEFAULT '',
                status TEXT NOT NULL,
                duration_secs INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE import_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                spotify_url TEXT NOT NULL,
                name TEXT NOT NULL,
                total_tracks INTEGER NOT NULL,
                completed_tracks INTEGER NOT NULL DEFAULT 0,
                failed_tracks INTEGER NOT NULL DEFAULT 0,
                skipped_tracks INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE import_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                spotify_url TEXT DEFAULT '',
                year TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()
        conn.close()

        db = Database(db_path)
        cols = {row[1] for row in db.connection.execute("PRAGMA table_info(download_history)")}
        assert "chat_id" in cols
        assert "spotify_url" in cols
        version = db.connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == 4
        tables = {row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "chat_prefs" in tables
        db.close()


class TestDatabaseClose:
    """Test close() method (lines 97-98)."""

    def test_database_close(self, tmp_path):
        """Verify close() works without error."""
        db_path = str(tmp_path / "close.db")
        db = Database(db_path)
        db.close()

    def test_database_double_close(self, tmp_path):
        """Double close should not raise."""
        db_path = str(tmp_path / "dblclose.db")
        db = Database(db_path)
        db.close()
        db.close()  # Should not raise due to contextlib.suppress

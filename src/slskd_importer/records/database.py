from __future__ import annotations

import atexit
import contextlib
import logging
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS download_history (
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    chat_id INTEGER,
    spotify_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS import_jobs (
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

CREATE TABLE IF NOT EXISTS import_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
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
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(job_id, position)
);

CREATE TABLE IF NOT EXISTS chat_prefs (
    chat_id INTEGER PRIMARY KEY,
    quality_preference TEXT NOT NULL DEFAULT '',
    locale TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_import_tracks_job_status ON import_tracks(job_id, status);
CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);
CREATE INDEX IF NOT EXISTS idx_download_history_created ON download_history(created_at);
CREATE INDEX IF NOT EXISTS idx_download_history_chat ON download_history(chat_id, created_at);
"""


def _open_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conn.close()
        raise
    return conn


class Database:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.RLock()
        try:
            self._conn = _open_connection(db_path)
            self._init_schema()
        except sqlite3.DatabaseError:
            failed_conn = getattr(self, "_conn", None)
            if failed_conn is not None:
                with contextlib.suppress(Exception):
                    failed_conn.close()
                self._conn = None
            backup = f"{db_path}.bak.{int(time.time())}"
            logger.warning("Database corrupt or unreadable at %s — backing up to %s and recreating", db_path, backup)
            for suffix in ("", "-wal", "-shm"):
                src = f"{db_path}{suffix}"
                if os.path.exists(src):
                    dest = f"{backup}{suffix}"
                    try:
                        os.replace(src, dest)
                    except OSError:
                        # Windows can hold a brief lock after close; copy then unlink.
                        shutil.copy2(src, dest)
                        with contextlib.suppress(OSError):
                            os.remove(src)
            self._conn = _open_connection(db_path)
            self._init_schema()
        atexit.register(self.close)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        """Serialize all SQLite access. Needed when history/import writes run in to_thread."""
        with self._lock:
            yield self._conn

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        self._conn.commit()

    def _migrate(self) -> None:
        """Apply additive migrations for databases created on older schemas."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(download_history)")}
        if "chat_id" not in cols:
            self._conn.execute("ALTER TABLE download_history ADD COLUMN chat_id INTEGER")
        if "spotify_url" not in cols:
            self._conn.execute("ALTER TABLE download_history ADD COLUMN spotify_url TEXT DEFAULT ''")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_history_chat ON download_history(chat_id, created_at)"
        )
        prefs_exists = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_prefs'"
        ).fetchone()
        if prefs_exists:
            prefs_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(chat_prefs)")}
            if "locale" not in prefs_cols:
                self._conn.execute("ALTER TABLE chat_prefs ADD COLUMN locale TEXT")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

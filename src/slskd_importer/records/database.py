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

_SCHEMA_VERSION = 9

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

CREATE TABLE IF NOT EXISTS queue_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'track',
    source_url TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT 'library',
    status TEXT NOT NULL DEFAULT 'active',
    message_id INTEGER,
    query_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES queue_batches(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    spotify_url TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    saved_name TEXT NOT NULL DEFAULT '',
    quality TEXT NOT NULL DEFAULT '',
    history_id INTEGER,
    forced INTEGER NOT NULL DEFAULT 0,
    pick TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(batch_id, position)
);

CREATE TABLE IF NOT EXISTS chat_prefs (
    chat_id INTEGER PRIMARY KEY,
    quality_preference TEXT NOT NULL DEFAULT '',
    locale TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sweep_songs (
    file TEXT PRIMARY KEY,
    stem TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    tier TEXT NOT NULL,
    audit TEXT NOT NULL,
    last_checked_at REAL,
    outcome TEXT,
    detail TEXT NOT NULL DEFAULT '',
    declined_at REAL
);

CREATE TABLE IF NOT EXISTS sweep_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    force INTEGER NOT NULL DEFAULT 0,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    current TEXT NOT NULL DEFAULT '',
    counts TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS sweep_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stem TEXT NOT NULL,
    current_path TEXT NOT NULL,
    proposal_path TEXT NOT NULL,
    proposal_ext TEXT NOT NULL,
    both_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    current_desc TEXT NOT NULL DEFAULT '',
    proposal_desc TEXT NOT NULL DEFAULT '',
    current_len REAL,
    proposal_len REAL,
    current_cutoff REAL,
    proposal_cutoff REAL,
    similarity REAL,
    run_id INTEGER,
    current_sound TEXT NOT NULL DEFAULT '',
    proposal_sound TEXT NOT NULL DEFAULT '',
    decline_reason TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    offered_at REAL,
    decided_at REAL,
    decision TEXT
);

CREATE TABLE IF NOT EXISTS sweep_replacements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stem TEXT NOT NULL,
    new_path TEXT NOT NULL,
    parked_path TEXT NOT NULL,
    from_desc TEXT NOT NULL DEFAULT '',
    to_desc TEXT NOT NULL DEFAULT '',
    how TEXT NOT NULL,
    run_id INTEGER,
    replaced_at REAL NOT NULL,
    purged_at REAL
);

CREATE INDEX IF NOT EXISTS idx_queue_items_batch_status ON queue_items(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_queue_items_status ON queue_items(status);
CREATE INDEX IF NOT EXISTS idx_queue_batches_status ON queue_batches(status, chat_id);
CREATE INDEX IF NOT EXISTS idx_download_history_created ON download_history(created_at);
CREATE INDEX IF NOT EXISTS idx_download_history_chat ON download_history(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sweep_reviews_pending ON sweep_reviews(decision, stem);
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
        # v8 replaced playlist imports with the download queue. The old import_jobs /
        # import_tracks tables are left in place, unused, so a rollback still finds them.
        item_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(queue_items)")}
        if "pick" not in item_cols:
            self._conn.execute("ALTER TABLE queue_items ADD COLUMN pick TEXT NOT NULL DEFAULT ''")
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

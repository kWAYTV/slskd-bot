from __future__ import annotations

from dataclasses import dataclass

from slskd_importer.history.record import HistoryRecord
from slskd_importer.records.database import Database


@dataclass
class HistoryStats:
    total: int
    success: int
    rejected: int
    failed: int
    undone: int
    delivered: int
    top_sources: list[tuple[str, int]]


class HistoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self,
        artist: str,
        title: str,
        filename: str,
        source_user: str,
        status: str,
        album: str = "",
        remote_path: str = "",
        duration_secs: int = 0,
        file_size: int = 0,
        chat_id: int | None = None,
        spotify_url: str = "",
    ) -> int:
        with self._db.locked() as conn:
            cursor = conn.execute(
                """INSERT INTO download_history
                (artist, title, album, filename, source_user, remote_path, status, duration_secs, file_size, chat_id, spotify_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artist,
                    title,
                    album,
                    filename,
                    source_user,
                    remote_path,
                    status,
                    duration_secs,
                    file_size,
                    chat_id,
                    spotify_url,
                ),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get_recent(self, limit: int = 50, chat_id: int | None = None) -> list[HistoryRecord]:
        with self._db.locked() as conn:
            if chat_id is None:
                cursor = conn.execute(
                    "SELECT * FROM download_history ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                )
                return [HistoryRecord(**dict(row)) for row in cursor.fetchall()]

            cursor = conn.execute(
                "SELECT * FROM download_history WHERE chat_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (chat_id, limit),
            )
            return [HistoryRecord(**dict(row)) for row in cursor.fetchall()]

    def find_success(
        self,
        artist: str,
        title: str,
        spotify_url: str = "",
        chat_id: int | None = None,
    ) -> HistoryRecord | None:
        """Return the most recent successful download for this track, if any."""
        params: list = []
        clauses = ["status = 'success'"]
        if spotify_url:
            clauses.append("(spotify_url = ? OR (lower(artist) = ? AND lower(title) = ?))")
            params.extend([spotify_url, artist.lower(), title.lower()])
        else:
            clauses.append("lower(artist) = ? AND lower(title) = ?")
            params.extend([artist.lower(), title.lower()])
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        sql = f"SELECT * FROM download_history WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC LIMIT 1"
        with self._db.locked() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            return HistoryRecord(**dict(row)) if row else None

    def get_last_saved(self, chat_id: int) -> HistoryRecord | None:
        """Most recent library save for this chat (undo target)."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_history WHERE chat_id = ? AND status = 'success' "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (chat_id,),
            )
            row = cursor.fetchone()
            return HistoryRecord(**dict(row)) if row else None

    def get_for_chat(self, entry_id: int, chat_id: int) -> HistoryRecord | None:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_history WHERE id = ? AND chat_id = ?",
                (entry_id, chat_id),
            )
            row = cursor.fetchone()
            return HistoryRecord(**dict(row)) if row else None

    def set_status(self, entry_id: int, status: str) -> None:
        with self._db.locked() as conn:
            conn.execute("UPDATE download_history SET status = ? WHERE id = ?", (status, entry_id))
            conn.commit()

    def summarize(self, chat_id: int) -> HistoryStats:
        with self._db.locked() as conn:

            def _count(status: str | None = None) -> int:
                if status is None:
                    return conn.execute(
                        "SELECT COUNT(*) FROM download_history WHERE chat_id = ?",
                        (chat_id,),
                    ).fetchone()[0]
                return conn.execute(
                    "SELECT COUNT(*) FROM download_history WHERE chat_id = ? AND status = ?",
                    (chat_id, status),
                ).fetchone()[0]

            sources = conn.execute(
                """SELECT source_user, COUNT(*) AS n FROM download_history
                   WHERE chat_id = ? AND status = 'success'
                   GROUP BY source_user ORDER BY n DESC LIMIT 5""",
                (chat_id,),
            ).fetchall()
            return HistoryStats(
                total=_count(),
                success=_count("success"),
                rejected=_count("rejected"),
                failed=_count("failed"),
                undone=_count("undone"),
                delivered=_count("delivered"),
                top_sources=[(row[0], row[1]) for row in sources],
            )

    def count(self, chat_id: int | None = None) -> int:
        with self._db.locked() as conn:
            if chat_id is None:
                return conn.execute("SELECT COUNT(*) FROM download_history").fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM download_history WHERE chat_id = ?", (chat_id,)).fetchone()[0]

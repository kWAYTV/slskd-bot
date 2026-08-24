from __future__ import annotations

from dataclasses import dataclass

from music_downloader.history.record import HistoryRecord
from music_downloader.records.database import Database


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
        self._conn = db.connection

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
        cursor = self._conn.execute(
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
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_recent(self, limit: int = 50, chat_id: int | None = None) -> list[HistoryRecord]:
        if chat_id is None:
            cursor = self._conn.execute(
                "SELECT * FROM download_history ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            )
            return [HistoryRecord(**dict(row)) for row in cursor.fetchall()]

        cursor = self._conn.execute(
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
            # Match by URL when available, but fall back to artist/title so
            # rows written before the spotify_url column existed still count.
            clauses.append("(spotify_url = ? OR (lower(artist) = ? AND lower(title) = ?))")
            params.extend([spotify_url, artist.lower(), title.lower()])
        else:
            clauses.append("lower(artist) = ? AND lower(title) = ?")
            params.extend([artist.lower(), title.lower()])
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        sql = f"SELECT * FROM download_history WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC LIMIT 1"
        cursor = self._conn.execute(sql, params)
        row = cursor.fetchone()
        return HistoryRecord(**dict(row)) if row else None

    def get_last_saved(self, chat_id: int) -> HistoryRecord | None:
        """Most recent library save for this chat (undo target)."""
        cursor = self._conn.execute(
            "SELECT * FROM download_history WHERE chat_id = ? AND status = 'success' "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (chat_id,),
        )
        row = cursor.fetchone()
        return HistoryRecord(**dict(row)) if row else None

    def get_for_chat(self, entry_id: int, chat_id: int) -> HistoryRecord | None:
        cursor = self._conn.execute(
            "SELECT * FROM download_history WHERE id = ? AND chat_id = ?",
            (entry_id, chat_id),
        )
        row = cursor.fetchone()
        return HistoryRecord(**dict(row)) if row else None

    def set_status(self, entry_id: int, status: str) -> None:
        self._conn.execute("UPDATE download_history SET status = ? WHERE id = ?", (status, entry_id))
        self._conn.commit()

    def summarize(self, chat_id: int) -> HistoryStats:
        def _count(status: str | None = None) -> int:
            if status is None:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM download_history WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()[0]
            return self._conn.execute(
                "SELECT COUNT(*) FROM download_history WHERE chat_id = ? AND status = ?",
                (chat_id, status),
            ).fetchone()[0]

        sources = self._conn.execute(
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
        if chat_id is None:
            return self._conn.execute("SELECT COUNT(*) FROM download_history").fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM download_history WHERE chat_id = ?", (chat_id,)).fetchone()[0]

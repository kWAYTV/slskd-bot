from __future__ import annotations

from music_downloader.history.record import HistoryRecord
from music_downloader.records.database import Database


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
        else:
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
            clauses.append("spotify_url = ?")
            params.append(spotify_url)
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

    def count(self, chat_id: int | None = None) -> int:
        if chat_id is None:
            cursor = self._conn.execute("SELECT COUNT(*) FROM download_history")
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM download_history WHERE chat_id = ?", (chat_id,))
        return cursor.fetchone()[0]

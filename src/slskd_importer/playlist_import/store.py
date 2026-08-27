from __future__ import annotations

from slskd_importer.playlist_import.job import ImportJob, ImportTrack, JobStatus, TrackStatus
from slskd_importer.records.database import Database

_COUNTER_COLUMN = {
    TrackStatus.completed: "completed_tracks",
    TrackStatus.failed: "failed_tracks",
    TrackStatus.skipped: "skipped_tracks",
}


class ImportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_job(self, chat_id: int, spotify_url: str, name: str, total_tracks: int) -> int:
        with self._db.locked() as conn:
            cursor = conn.execute(
                """INSERT INTO import_jobs (chat_id, spotify_url, name, total_tracks)
                VALUES (?, ?, ?, ?)""",
                (chat_id, spotify_url, name, total_tracks),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get_active_job(self, chat_id: int) -> ImportJob | None:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM import_jobs WHERE chat_id = ? AND status IN ('pending', 'active') LIMIT 1",
                (chat_id,),
            )
            row = cursor.fetchone()
            return ImportJob(**dict(row)) if row else None

    def update_job_status(self, job_id: int, status: JobStatus) -> None:
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE import_jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status.value, job_id),
            )
            conn.commit()

    def complete_track(self, job_id: int, track_id: int, status: TrackStatus, error_message: str = "") -> None:
        """Atomically update track status and increment the job counter in one transaction."""
        col = _COUNTER_COLUMN.get(status)
        with self._db.locked() as conn:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    "UPDATE import_tracks SET status = ?, error_message = ?, updated_at = datetime('now') WHERE id = ?",
                    (status.value, error_message, track_id),
                )
                if col:
                    conn.execute(
                        f"UPDATE import_jobs SET {col} = {col} + 1, updated_at = datetime('now') WHERE id = ?",
                        (job_id,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def update_track_status(self, track_id: int, status: TrackStatus, error_message: str = "") -> None:
        """Update track status only (no counter increment). Used for intermediate states like 'searching'."""
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE import_tracks SET status = ?, error_message = ?, updated_at = datetime('now') WHERE id = ?",
                (status.value, error_message, track_id),
            )
            conn.commit()

    def add_tracks(self, job_id: int, tracks: list[dict]) -> None:
        with self._db.locked() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO import_tracks (job_id, position, artist, title, album, duration_ms, spotify_url, year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        job_id,
                        t["position"],
                        t["artist"],
                        t["title"],
                        t.get("album", ""),
                        t.get("duration_ms", 0),
                        t.get("spotify_url", ""),
                        t.get("year", ""),
                    )
                    for t in tracks
                ],
            )
            conn.commit()

    def get_next_pending_track(self, job_id: int) -> ImportTrack | None:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM import_tracks WHERE job_id = ? AND status = 'pending' ORDER BY position LIMIT 1",
                (job_id,),
            )
            row = cursor.fetchone()
            return ImportTrack(**dict(row)) if row else None

    def get_tracks_by_job(self, job_id: int) -> list[ImportTrack]:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM import_tracks WHERE job_id = ? ORDER BY position",
                (job_id,),
            )
            return [ImportTrack(**dict(row)) for row in cursor.fetchall()]

    def get_job_progress(self, job_id: int) -> tuple[int, int, int, int]:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT completed_tracks, failed_tracks, skipped_tracks, total_tracks FROM import_jobs WHERE id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                return (0, 0, 0, 0)
            return (row["completed_tracks"], row["failed_tracks"], row["skipped_tracks"], row["total_tracks"])

    def get_job_for_chat(self, job_id: int, chat_id: int) -> ImportJob | None:
        """Get a job only if it belongs to the specified chat (IDOR prevention)."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM import_jobs WHERE id = ? AND chat_id = ?",
                (job_id, chat_id),
            )
            row = cursor.fetchone()
            return ImportJob(**dict(row)) if row else None

    def list_resumable_jobs(self) -> list[ImportJob]:
        """Jobs left active/pending across a bot restart."""
        with self._db.locked() as conn:
            cursor = conn.execute("SELECT * FROM import_jobs WHERE status IN ('pending', 'active') ORDER BY id")
            return [ImportJob(**dict(row)) for row in cursor.fetchall()]

    def get_failed_tracks(self, job_id: int) -> list[ImportTrack]:
        with self._db.locked() as conn:
            cursor = conn.execute(
                "SELECT * FROM import_tracks WHERE job_id = ? AND status = 'failed' ORDER BY position",
                (job_id,),
            )
            return [ImportTrack(**dict(row)) for row in cursor.fetchall()]

    def reset_failed_tracks(self, job_id: int) -> int:
        """Set failed tracks back to pending (and fix the job counter) so they can be retried."""
        with self._db.locked() as conn:
            try:
                conn.execute("BEGIN")
                cursor = conn.execute(
                    """UPDATE import_tracks SET status = 'pending', error_message = '', updated_at = datetime('now')
                    WHERE job_id = ? AND status = 'failed'""",
                    (job_id,),
                )
                reset = cursor.rowcount
                if reset:
                    conn.execute(
                        "UPDATE import_jobs SET failed_tracks = failed_tracks - ?, status = 'active', "
                        "updated_at = datetime('now') WHERE id = ?",
                        (reset, job_id),
                    )
                conn.commit()
                return reset
            except Exception:
                conn.rollback()
                raise

    def reset_in_flight_tracks(self, job_id: int) -> int:
        """Reset searching/awaiting tracks to pending so a resumed job can retry them."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                """UPDATE import_tracks SET status = 'pending', error_message = '', updated_at = datetime('now')
                WHERE job_id = ? AND status IN ('searching', 'awaiting_approval')""",
                (job_id,),
            )
            conn.commit()
            return cursor.rowcount

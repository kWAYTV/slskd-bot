"""SQLite persistence for the download queue."""

from __future__ import annotations

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.batch import Batch, Destination, Item, ItemStatus
from slskd_importer.records.database import Database
from slskd_importer.sources.tracklist import Entry

_ITEM_FIELDS = frozenset({"status", "detail", "saved_name", "quality", "history_id", "forced", "pick"})

# Fair order: the batch with the fewest tracks in flight goes first, so one song
# never waits behind a 300-track playlist.
_NEXT_PENDING = """
SELECT i.* FROM queue_items i
JOIN queue_batches b ON b.id = i.batch_id
WHERE i.status = 'pending' AND b.status = 'active'
ORDER BY (SELECT COUNT(*) FROM queue_items w WHERE w.batch_id = i.batch_id AND w.status = 'working'),
         b.id, i.position
LIMIT 1
"""


class QueueRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------------------------------------------------------------- batches

    def create_batch(
        self,
        chat_id: int,
        user_id: int,
        name: str,
        kind: str,
        entries: list[Entry],
        *,
        source_url: str = "",
        destination: Destination = Destination.library,
        message_id: int | None = None,
        query_message_id: int | None = None,
    ) -> Batch:
        """Insert a batch and its items in one transaction."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "INSERT INTO queue_batches (chat_id, user_id, name, kind, source_url, destination, message_id, "
                "query_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, name, kind, source_url, str(destination), message_id, query_message_id),
            )
            batch_id = cursor.lastrowid
            conn.executemany(
                "INSERT INTO queue_items (batch_id, position, query, artist, title, album, duration_ms, spotify_url, "
                "year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_item_row(batch_id, position, entry) for position, entry in enumerate(entries, start=1)],
            )
            conn.commit()
            row = conn.execute("SELECT * FROM queue_batches WHERE id = ?", (batch_id,)).fetchone()
            return Batch(**dict(row))

    def get_batch(self, batch_id: int) -> Batch | None:
        with self._db.locked() as conn:
            row = conn.execute("SELECT * FROM queue_batches WHERE id = ?", (batch_id,)).fetchone()
            return Batch(**dict(row)) if row else None

    def get_batch_for_chat(self, batch_id: int, chat_id: int) -> Batch | None:
        """A batch only when it belongs to *chat_id*: buttons cannot reach another chat's queue."""
        batch = self.get_batch(batch_id)
        return batch if batch is not None and batch.chat_id == chat_id else None

    def active_batches(self, chat_id: int | None = None) -> list[Batch]:
        sql = "SELECT * FROM queue_batches WHERE status = 'active'"
        params: tuple = ()
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params = (chat_id,)
        with self._db.locked() as conn:
            return [Batch(**dict(row)) for row in conn.execute(sql + " ORDER BY id", params).fetchall()]

    def open_batches(self, chat_id: int, limit: int = 10) -> list[Batch]:
        """The chat's batches that are still working or have tracks waiting for a decision, newest first."""
        with self._db.locked() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_batches b WHERE b.chat_id = ? AND (b.status = 'active' OR EXISTS ("
                "SELECT 1 FROM queue_items i WHERE i.batch_id = b.id AND i.status IN ('choose', 'review', 'doubt'))) "
                "ORDER BY b.id DESC LIMIT ?",
                (chat_id, limit),
            )
            return [Batch(**dict(row)) for row in rows.fetchall()]

    def next_waiting(self, batch_id: int, after_position: int = 0) -> Item | None:
        """The next track waiting for a pick, after *after_position*, wrapping round to the first one."""
        with self._db.locked() as conn:
            row = conn.execute(
                "SELECT * FROM queue_items WHERE batch_id = ? AND status = 'choose' "
                "ORDER BY (position <= ?), position LIMIT 1",
                (batch_id, after_position),
            ).fetchone()
            return Item(**dict(row)) if row else None

    def skip_waiting(self, batch_id: int) -> int:
        """Let go of every track still waiting for a pick; returns how many."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "UPDATE queue_items SET status = 'cancelled', updated_at = datetime('now') "
                "WHERE batch_id = ? AND status IN ('choose', 'review')",
                (batch_id,),
            )
            conn.commit()
            return cursor.rowcount

    def recent_batches(self, chat_id: int, limit: int) -> list[Batch]:
        """The chat's latest batches, newest first, whatever their status."""
        with self._db.locked() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_batches WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)
            )
            return [Batch(**dict(row)) for row in rows.fetchall()]

    def set_message(self, batch_id: int, message_id: int) -> None:
        with self._db.locked() as conn:
            conn.execute("UPDATE queue_batches SET message_id = ? WHERE id = ?", (message_id, batch_id))
            conn.commit()

    def cancel_batch(self, batch_id: int) -> None:
        """Stop a batch: its open items are cancelled, finished ones stay as they are."""
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE queue_items SET status = 'cancelled', updated_at = datetime('now') "
                "WHERE batch_id = ? AND status IN ('pending', 'working')",
                (batch_id,),
            )
            conn.execute(
                "UPDATE queue_batches SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
                (batch_id,),
            )
            conn.commit()

    def close_if_finished(self, batch_id: int) -> bool:
        """Mark an active batch done once no item is pending or working. True when it was closed now."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "UPDATE queue_batches SET status = 'done', updated_at = datetime('now') "
                "WHERE id = ? AND status = 'active' AND NOT EXISTS "
                "(SELECT 1 FROM queue_items WHERE batch_id = ? AND status IN ('pending', 'working'))",
                (batch_id, batch_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ items

    def items(self, batch_id: int) -> list[Item]:
        with self._db.locked() as conn:
            rows = conn.execute("SELECT * FROM queue_items WHERE batch_id = ? ORDER BY position", (batch_id,))
            return [Item(**dict(row)) for row in rows.fetchall()]

    def get_item(self, item_id: int) -> Item | None:
        with self._db.locked() as conn:
            row = conn.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            return Item(**dict(row)) if row else None

    def counts(self, batch_id: int) -> dict[str, int]:
        with self._db.locked() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM queue_items WHERE batch_id = ? GROUP BY status", (batch_id,)
            )
            return {row["status"]: row["n"] for row in rows.fetchall()}

    def claim_next(self) -> Item | None:
        """Take the next pending item of any active batch and mark it working."""
        with self._db.locked() as conn:
            row = conn.execute(_NEXT_PENDING).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE queue_items SET status = 'working', updated_at = datetime('now') WHERE id = ?", (row["id"],)
            )
            conn.commit()
            return Item(**{**dict(row), "status": ItemStatus.working.value})

    def update_item(self, item_id: int, **fields: object) -> None:
        """Set item columns (status, detail, saved_name, quality, history_id, forced)."""
        unknown = set(fields) - _ITEM_FIELDS
        if unknown:
            raise ValueError(f"not item columns: {', '.join(sorted(unknown))}")
        if "status" in fields:
            fields["status"] = str(fields["status"])
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._db.locked() as conn:
            conn.execute(
                f"UPDATE queue_items SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                (*fields.values(), item_id),
            )
            conn.commit()

    def batch_of_message(self, chat_id: int, message_id: int) -> Batch | None:
        """The batch whose card is that chat message, or None."""
        with self._db.locked() as conn:
            row = conn.execute(
                "SELECT * FROM queue_batches WHERE chat_id = ? AND message_id = ? ORDER BY id DESC LIMIT 1",
                (chat_id, message_id),
            ).fetchone()
            return Batch(**dict(row)) if row else None

    def rename_item(self, item_id: int, query: str) -> None:
        """The requester says which song an item really is: start it over under that name.

        Its identity, pick and remembered copies belonged to the wrong song and go; a file
        already saved for it stays until a copy of the right song replaces it.
        """
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE queue_items SET query = ?, artist = '', title = '', album = '', duration_ms = 0, "
                "spotify_url = '', year = '', status = 'pending', detail = '', pick = '', forced = 0, "
                "updated_at = datetime('now') WHERE id = ?",
                (query, item_id),
            )
            conn.execute("DELETE FROM queue_copies WHERE item_id = ?", (item_id,))
            conn.execute(
                "UPDATE queue_batches SET status = 'active', updated_at = datetime('now') "
                "WHERE id = (SELECT batch_id FROM queue_items WHERE id = ?)",
                (item_id,),
            )
            conn.commit()

    def set_identity(self, item_id: int, track: TrackInfo) -> None:
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE queue_items SET artist = ?, title = ?, album = ?, duration_ms = ?, spotify_url = ?, year = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (track.artist, track.title, track.album, track.duration_ms, track.spotify_url, track.year, item_id),
            )
            conn.commit()

    def requeue(self, item_id: int, *, forced: bool = False, pick: str | None = None) -> None:
        """Send one item through the queue again and reopen its batch.

        *pick*: the hand-picked copy to fetch (JSON), "" to let the queue search again, None to keep
        whatever pick the item already has.
        """
        with self._db.locked() as conn:
            conn.execute(
                "UPDATE queue_items SET status = 'pending', detail = '', forced = ?, pick = COALESCE(?, pick), "
                "updated_at = datetime('now') WHERE id = ?",
                (int(forced), pick, item_id),
            )
            conn.execute(
                "UPDATE queue_batches SET status = 'active', updated_at = datetime('now') "
                "WHERE id = (SELECT batch_id FROM queue_items WHERE id = ?)",
                (item_id,),
            )
            conn.commit()

    def requeue_failed(self, batch_id: int) -> int:
        """Send the batch's failed and unmatched items through the queue again; returns how many."""
        with self._db.locked() as conn:
            cursor = conn.execute(
                "UPDATE queue_items SET status = 'pending', detail = '', updated_at = datetime('now') "
                "WHERE batch_id = ? AND status IN ('failed', 'no_match')",
                (batch_id,),
            )
            if cursor.rowcount:
                conn.execute(
                    "UPDATE queue_batches SET status = 'active', updated_at = datetime('now') WHERE id = ?",
                    (batch_id,),
                )
            conn.commit()
            return cursor.rowcount

    def save_copies(self, item_id: int, lossy: bool, copies: str) -> None:
        """Remember the copies found for an item (JSON, see queue.pick), replacing an earlier search."""
        with self._db.locked() as conn:
            conn.execute(
                "INSERT INTO queue_copies (item_id, lossy, copies) VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET lossy = excluded.lossy, copies = excluded.copies, "
                "found_at = datetime('now')",
                (item_id, int(lossy), copies),
            )
            conn.commit()

    def load_copies(self, item_id: int) -> tuple[bool, str] | None:
        """(no lossless copy was found, the copies as JSON) for an item, or None when it was never searched."""
        with self._db.locked() as conn:
            row = conn.execute("SELECT lossy, copies FROM queue_copies WHERE item_id = ?", (item_id,)).fetchone()
            return (bool(row["lossy"]), row["copies"]) if row else None

    def reset_working(self) -> int:
        """After a restart: items that were in flight go back to pending. Returns how many."""
        with self._db.locked() as conn:
            cursor = conn.execute("UPDATE queue_items SET status = 'pending' WHERE status = 'working'")
            conn.commit()
            return cursor.rowcount


def _item_row(batch_id: int, position: int, entry: Entry) -> tuple:
    track = entry.track
    if track is None:
        return (batch_id, position, entry.query, "", "", "", 0, "", "")
    return (
        batch_id,
        position,
        entry.query or track.filename,
        track.artist,
        track.title,
        track.album,
        track.duration_ms,
        track.spotify_url,
        track.year,
    )

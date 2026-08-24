"""Per-chat preference persistence."""

from __future__ import annotations

from slskd_importer.records.database import Database


class ChatPrefsRepository:
    def __init__(self, db: Database) -> None:
        self._conn = db.connection

    def get_quality(self, chat_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT quality_preference FROM chat_prefs WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return row[0] if row else None

    def set_quality(self, chat_id: int, preference: str) -> None:
        self._conn.execute(
            """INSERT INTO chat_prefs (chat_id, quality_preference, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(chat_id) DO UPDATE SET
                 quality_preference = excluded.quality_preference,
                 updated_at = datetime('now')""",
            (chat_id, preference),
        )
        self._conn.commit()

    def load_all_quality(self) -> dict[int, str]:
        rows = self._conn.execute("SELECT chat_id, quality_preference FROM chat_prefs").fetchall()
        return {int(row[0]): row[1] for row in rows}

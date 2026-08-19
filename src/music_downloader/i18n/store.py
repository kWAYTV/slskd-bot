"""Persist each Telegram user's chosen locale in SQLite."""

from __future__ import annotations

from music_downloader.i18n.catalog import DEFAULT_LOCALE, SUPPORTED_LOCALES
from music_downloader.records.database import Database


class LocaleStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[int, str] = {}

    def get(self, user_id: int) -> str | None:
        cached = self._cache.get(user_id)
        if cached is not None:
            return cached
        row = self._db.connection.execute(
            "SELECT locale FROM user_locales WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        locale = row["locale"]
        if locale not in SUPPORTED_LOCALES:
            return None
        self._cache[user_id] = locale
        return locale

    def set(self, user_id: int, locale: str) -> str:
        resolved = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        self._db.connection.execute(
            """
            INSERT INTO user_locales (user_id, locale, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                locale = excluded.locale,
                updated_at = datetime('now')
            """,
            (user_id, resolved),
        )
        self._db.connection.commit()
        self._cache[user_id] = resolved
        return resolved

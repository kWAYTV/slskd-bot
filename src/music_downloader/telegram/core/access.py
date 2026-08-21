"""Authorization gates for bot commands and callbacks.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

from telegram import Update


def is_authorized(self, user_id: int) -> bool:
    if not self.config.telegram_allowed_users:
        return False
    return user_id in self.config.telegram_allowed_users


def can_save_library(self, user_id: int | None) -> bool:
    """Library save is allowed for all authorized users unless TELEGRAM_LIBRARY_USERS is set."""
    library_users = getattr(self.config, "telegram_library_users", None)
    if not isinstance(library_users, (set, frozenset)):
        return True
    if not library_users:
        return True
    if user_id is None:
        return False
    return user_id in library_users


async def check_auth(self, update: Update) -> bool:
    if not self._is_authorized(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this bot.")
        return False
    return True


async def check_library_auth(self, update: Update) -> bool:
    if not await self._check_auth(update):
        return False
    if not self._can_save_library(update.effective_user.id):
        await update.message.reply_text(
            "You can search and download files, but only library users can save to the music library or import playlists."
        )
        return False
    return True

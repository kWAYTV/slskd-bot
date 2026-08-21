"""Pasted Spotify track links — resolve metadata, then search Soulseek."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from music_downloader.catalog.links import extract_spotify_track_id
from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.playlist_import.command import start_import_from_url
from music_downloader.telegram.ui.editing import safe_edit

logger = logging.getLogger(__name__)


async def handle_link_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query: str) -> bool:
    """Handle pasted Spotify links. Returns True when the message was a link."""
    if PlaylistResolver.is_spotify_url(query):
        # Pasted playlist/album link — start the import directly instead of
        # bouncing the user to /import.
        if not await self._check_library_auth(update):
            return True
        await start_import_from_url(self, update, context, chat_id, query.split()[0])
        return True

    spotify_track_id = extract_spotify_track_id(query)
    if spotify_track_id:
        await _search_from_spotify_link(self, update, context, chat_id, spotify_track_id)
        return True

    return False


async def _search_from_spotify_link(self, update, context, chat_id: int, track_id: str):
    """Resolve a pasted Spotify track link directly (no search ambiguity) and hit Soulseek."""
    await self._cancel_chat_operations(chat_id)
    generation = self._chat_generation[chat_id]

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔗 Resolving Spotify track link...",
    )

    track = await asyncio.to_thread(self.spotify.get_track, track_id)
    if self._is_stale(chat_id, generation):
        return
    if not track:
        await safe_edit(searching_msg, "Could not resolve that Spotify track link. Try the song name instead.")
        return

    self.pending[chat_id] = PendingSearch(
        query=f"{track.artist} {track.title}",
        track=track,
        user_id=update.effective_user.id,
    )
    await self._do_slskd_search(context, chat_id, track, searching_msg, generation)

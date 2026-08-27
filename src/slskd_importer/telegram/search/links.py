"""Pasted Spotify track links — resolve metadata, then search Soulseek."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.catalog.links import extract_spotify_track_id
from slskd_importer.catalog.playlist import PlaylistResolver
from slskd_importer.telegram.core.session import PendingSearch
from slskd_importer.telegram.playlist_import.command import start_import_from_url
from slskd_importer.telegram.ui.editing import safe_edit

logger = logging.getLogger(__name__)


async def handle_link_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query: str) -> bool:
    """Handle pasted Spotify links. Returns True when the message was a link."""
    if PlaylistResolver.is_spotify_url(query):
        if not await self._check_library_auth(update):
            return True
        logger.info("chat=%s pasted playlist/album link", chat_id)
        await start_import_from_url(self, update, context, chat_id, query.split()[0])
        return True

    spotify_track_id = extract_spotify_track_id(query)
    if spotify_track_id:
        logger.info("chat=%s pasted Spotify track %s", chat_id, spotify_track_id)
        search_id = self._next_search_id()
        self.pending[search_id] = PendingSearch(
            query=query,
            chat_id=chat_id,
            search_id=search_id,
            user_id=update.effective_user.id,
        )
        await search_from_spotify_link(self, update, context, chat_id, spotify_track_id, search_id)
        return True

    return False


async def search_from_spotify_link(self, update, context, chat_id: int, track_id: str, search_id: str):
    """Resolve a pasted Spotify track link directly (no search ambiguity) and hit Soulseek."""
    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "resolving_link"),
    )
    search = self.pending.get(search_id)
    if search:
        search.message_id = searching_msg.message_id

    track = await asyncio.to_thread(self.spotify.get_track, track_id)
    if self._search_cancelled(search_id):
        return
    if not track:
        await safe_edit(searching_msg, self.t(chat_id, "link_failed"))
        return

    if search:
        search.track = track
        search.query = f"{track.artist} {track.title}"
    else:
        self.pending[search_id] = PendingSearch(
            query=f"{track.artist} {track.title}",
            track=track,
            chat_id=chat_id,
            search_id=search_id,
            user_id=update.effective_user.id,
            message_id=searching_msg.message_id,
        )
    await self._do_slskd_search(context, chat_id, track, searching_msg, search_id=search_id)

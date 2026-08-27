"""Free-text message entry point — song queries and link detection."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.catalog.links import extract_spotify_track_id
from slskd_importer.catalog.playlist import PlaylistResolver
from slskd_importer.telegram.core.session import PendingSearch
from slskd_importer.telegram.playlist_import.command import start_import_from_url
from slskd_importer.telegram.search.links import search_from_spotify_link

logger = logging.getLogger(__name__)


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — treat as song search queries.

    Returns immediately after scheduling work so the next update (another
    search, a download pick, /status) is not blocked. PTB wiki: use
    ``Application.create_task`` for long I/O; keep updates sequential.
    """
    if not await self._check_auth(update):
        return

    query = update.message.text.strip()
    if not query:
        return

    chat_id = update.effective_chat.id

    if PlaylistResolver.is_spotify_url(query):
        if not await self._check_library_auth(update):
            return
        logger.info("chat=%s pasted playlist/album link", chat_id)
        task = context.application.create_task(
            start_import_from_url(self, update, context, chat_id, query.split()[0]),
            update=update,
        )
        self._track_task(chat_id, task)
        return

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
        task = context.application.create_task(
            search_from_spotify_link(self, update, context, chat_id, spotify_track_id, search_id),
            update=update,
        )
        self._track_task(chat_id, task)
        return

    search_id = self._next_search_id()
    self.pending[search_id] = PendingSearch(
        query=query,
        chat_id=chat_id,
        search_id=search_id,
        user_id=update.effective_user.id,
    )
    logger.info("chat=%s user=%s search=%s query=%r", chat_id, update.effective_user.id, search_id, query)
    task = context.application.create_task(
        self._do_search(update, context, query, search_id),
        update=update,
    )
    self._track_task(chat_id, task)

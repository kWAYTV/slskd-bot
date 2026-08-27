"""Spotify candidate lookup: search, dedup/artist filtering, pick and paging."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.telegram.core.session import PendingSearch, split_search_callback
from slskd_importer.telegram.search.keyboards import build_direct_search_keyboard, build_spotify_keyboard
from slskd_importer.telegram.ui.editing import safe_edit, safe_query_edit
from slskd_importer.telegram.ui.formatting import format_spotify_results, track_md

logger = logging.getLogger(__name__)


async def do_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, search_id: str):
    """Resolve metadata via Spotify, then proceed to slskd search."""
    chat_id = update.effective_chat.id
    search = self.pending.get(search_id)
    if search is None:
        search = PendingSearch(
            query=query,
            chat_id=chat_id,
            search_id=search_id,
            user_id=update.effective_user.id,
        )
        self.pending[search_id] = search

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "looking_up", query=query),
        parse_mode=ParseMode.MARKDOWN,
    )
    search.message_id = searching_msg.message_id

    try:
        tracks = await asyncio.to_thread(self.spotify.search_multiple, query, 50)
        if self._search_cancelled(search_id):
            return

        logger.info("chat=%s search=%s Spotify returned %d track(s) for %r", chat_id, search_id, len(tracks), query)
        if not tracks:
            await safe_edit(
                searching_msg,
                self.t(chat_id, "spotify_not_found", query=query),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_direct_search_keyboard(search_id, locale=self.locale(chat_id)),
            )
            return

        unique_tracks = _filter_candidates(query, tracks)

        logger.debug("chat=%s search=%s Spotify candidates after filter: %d", chat_id, search_id, len(unique_tracks))
        if len(unique_tracks) == 1:
            search.track = unique_tracks[0]
            await self._do_slskd_search(context, chat_id, unique_tracks[0], searching_msg, search_id=search_id)
            return

        self._spotify_candidates[search_id] = unique_tracks
        self._spotify_page[search_id] = 0
        await safe_edit(
            searching_msg,
            format_spotify_results(unique_tracks, page=0, locale=self.locale(chat_id)),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=build_spotify_keyboard(
                unique_tracks, page=0, search_id=search_id, locale=self.locale(chat_id)
            ),
        )

    except Exception:
        logger.exception(f"Unexpected error in _do_search for: {query}")
        self._session.drop_search(search_id)
        await safe_edit(searching_msg, self.t(chat_id, "something_wrong"))


def _filter_candidates(query: str, tracks: list[TrackInfo]) -> list[TrackInfo]:
    """Dedup Spotify results and prefer candidates whose artist matches the query."""
    query_lower = query.lower()
    query_words = set(query_lower.split())
    query_artist = ""
    if " - " in query:
        query_artist = query.split(" - ", 1)[0].strip().lower()

    seen = set()
    artist_match_tracks = []
    other_tracks = []
    for t in tracks:
        key = (t.artist.lower(), t.title.lower(), t.album.lower())
        if key in seen:
            continue
        seen.add(key)
        artist_lower = t.artist.lower()
        if query_artist and query_artist not in artist_lower:
            continue
        artist_words = set(artist_lower.split())
        if (len(artist_words) >= 2 and artist_lower in query_lower) or artist_words.issubset(query_words):
            artist_match_tracks.append(t)
        else:
            other_tracks.append(t)

    artist_match_tracks.sort(key=lambda t: len(t.artist), reverse=True)
    unique_tracks = artist_match_tracks + other_tracks

    if not unique_tracks:
        # The artist filter emptied the list — fall back to plain dedup.
        seen = set()
        for t in tracks:
            key = (t.artist.lower(), t.title.lower(), t.album.lower())
            if key not in seen:
                seen.add(key)
                unique_tracks.append(t)

    return unique_tracks


async def handle_spotify_page(self, update, context, chat_id: int, data: str):
    """Handle Spotify page navigation (◀️ / ▶️)."""
    query = update.callback_query
    parsed = split_search_callback(data)
    if not parsed:
        return
    search_id, page_raw = parsed
    candidates = self._spotify_candidates.get(search_id)
    if not candidates:
        await safe_query_edit(query, self.t(chat_id, "search_expired"))
        return

    try:
        page = int(page_raw)
    except ValueError:
        return

    self._spotify_page[search_id] = page
    await safe_query_edit(
        query,
        format_spotify_results(candidates, page=page, locale=self.locale(chat_id)),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=build_spotify_keyboard(candidates, page=page, search_id=search_id, locale=self.locale(chat_id)),
    )


async def handle_spotify_selection(self, update, context, chat_id: int, data: str):
    """Handle Spotify track selection from multiple results."""
    query = update.callback_query
    parsed = split_search_callback(data)
    if not parsed:
        return
    search_id, action = parsed

    if action == "cancel":
        self._session.drop_search(search_id)
        await safe_query_edit(query, self.t(chat_id, "cancelled"))
        return

    candidates = self._spotify_candidates.get(search_id)
    if not candidates:
        self._session.drop_search(search_id)
        await safe_query_edit(query, self.t(chat_id, "cancelled"))
        return

    try:
        index = int(action)
    except ValueError:
        return

    if index >= len(candidates):
        return

    self._spotify_candidates.pop(search_id, None)
    self._spotify_page.pop(search_id, None)
    track = candidates[index]
    search = self.pending.get(search_id)
    if search:
        search.track = track
    await safe_query_edit(
        query,
        self.t(chat_id, "spotify_selected", track=track_md(track), duration=track.duration_display),
        parse_mode=ParseMode.MARKDOWN,
    )

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "searching_slskd"),
        parse_mode=ParseMode.MARKDOWN,
    )
    if search:
        search.message_id = searching_msg.message_id
    task = context.application.create_task(
        self._do_slskd_search(context, chat_id, track, searching_msg, search_id=search_id),
        update=update,
    )
    self._track_task(chat_id, task)

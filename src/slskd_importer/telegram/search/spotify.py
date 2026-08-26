"""Spotify candidate lookup: search, dedup/artist filtering, pick and paging."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.telegram.core.session import PendingSearch
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.formatting import format_spotify_results, track_md
from slskd_importer.telegram.ui.keyboards import build_direct_search_keyboard, build_spotify_keyboard

logger = logging.getLogger(__name__)


async def do_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, generation: int):
    """Resolve metadata via Spotify, then proceed to slskd search."""
    chat_id = update.effective_chat.id

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "looking_up", query=query),
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        tracks = self.spotify.search_multiple(query, limit=50)
        if self._is_stale(chat_id, generation):
            return

        logger.info("chat=%s Spotify returned %d track(s) for %r", chat_id, len(tracks), query)
        if not tracks:
            await safe_edit(
                searching_msg,
                self.t(chat_id, "spotify_not_found", query=query),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_direct_search_keyboard(locale=self.locale(chat_id)),
            )
            self.pending[chat_id] = PendingSearch(query=query, track=None, user_id=update.effective_user.id)
            return

        unique_tracks = _filter_candidates(query, tracks)

        logger.debug("chat=%s Spotify candidates after filter: %d", chat_id, len(unique_tracks))
        if len(unique_tracks) == 1:
            self.pending[chat_id] = PendingSearch(
                query=query,
                track=unique_tracks[0],
                user_id=update.effective_user.id,
            )
            await self._do_slskd_search(context, chat_id, unique_tracks[0], searching_msg, generation)
            return

        self._spotify_candidates[chat_id] = unique_tracks
        self._spotify_page[chat_id] = 0
        self.pending[chat_id] = PendingSearch(query=query, track=None, user_id=update.effective_user.id)
        await safe_edit(
            searching_msg,
            format_spotify_results(unique_tracks, page=0, locale=self.locale(chat_id)),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=build_spotify_keyboard(unique_tracks, page=0, locale=self.locale(chat_id)),
        )

    except Exception:
        logger.exception(f"Unexpected error in _do_search for: {query}")
        self._spotify_candidates.pop(chat_id, None)
        self._spotify_page.pop(chat_id, None)
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
    candidates = self._spotify_candidates.get(chat_id)
    if not candidates:
        await query.edit_message_text(self.t(chat_id, "search_expired"))
        return

    try:
        page = int(data.split(":", 1)[1])
    except ValueError:
        return

    self._spotify_page[chat_id] = page
    await query.edit_message_text(
        format_spotify_results(candidates, page=page, locale=self.locale(chat_id)),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=build_spotify_keyboard(candidates, page=page, locale=self.locale(chat_id)),
    )


async def handle_spotify_selection(self, update, context, chat_id: int, data: str):
    """Handle Spotify track selection from multiple results."""
    query = update.callback_query
    action = data.split(":", 1)[1]

    candidates = self._spotify_candidates.pop(chat_id, None)
    self._spotify_page.pop(chat_id, None)

    if action == "cancel" or not candidates:
        await query.edit_message_text(self.t(chat_id, "cancelled"))
        return

    try:
        index = int(action)
    except ValueError:
        return

    if index >= len(candidates):
        return

    track = candidates[index]
    await query.edit_message_text(
        self.t(chat_id, "spotify_selected", track=track_md(track), duration=track.duration_display),
        parse_mode=ParseMode.MARKDOWN,
    )

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "searching_slskd"),
        parse_mode=ParseMode.MARKDOWN,
    )
    generation = self._chat_generation.get(chat_id, 0)
    await self._do_slskd_search(context, chat_id, track, searching_msg, generation)

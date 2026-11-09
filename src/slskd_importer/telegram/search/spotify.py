"""Spotify candidate lookup: search, dedup/artist filtering, pick and paging."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.query import clean_query, parse_query_artist_title
from slskd_importer.telegram.core.session import PendingSearch, split_search_callback
from slskd_importer.telegram.search.keyboards import build_spotify_keyboard
from slskd_importer.telegram.ui.editing import safe_edit, safe_query_edit
from slskd_importer.telegram.ui.formatting import format_spotify_results, track_md
from slskd_importer.telegram.ui.markdown import escape_md

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
        tracks = await _lookup_tracks(self, query)
        if self._search_cancelled(search_id):
            return

        logger.info("chat=%s search=%s Spotify returned %d track(s) for %r", chat_id, search_id, len(tracks), query)
        if not tracks:
            # No catalog match: go straight to Soulseek instead of asking for another tap.
            await _fall_back_to_direct(self, context, chat_id, query, searching_msg, search_id)
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


async def _lookup_tracks(self, query: str) -> list[TrackInfo]:
    """Spotify candidates: field-filtered when the query names artist and title, free text otherwise."""
    cleaned = clean_query(query)
    artist, title = parse_query_artist_title(query)
    if artist and title and _has_separator(cleaned):
        tracks = await asyncio.to_thread(self.spotify.search_fielded, artist, title, 50)
        if tracks:
            return tracks
    return await asyncio.to_thread(self.spotify.search_multiple, cleaned, 50)


def _has_separator(query: str) -> bool:
    return any(sep in query for sep in (" - ", " – ", " — ", " | "))


async def _fall_back_to_direct(self, context, chat_id: int, query: str, searching_msg, search_id: str) -> None:
    """No Spotify match: tell the user what the file will be saved as and search Soulseek at once."""
    artist, title = parse_query_artist_title(query)
    await safe_edit(
        searching_msg,
        self.t(
            chat_id,
            "spotify_not_found_direct",
            query=escape_md(query),
            artist=escape_md(artist),
            title=escape_md(title),
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    await self._do_direct_slskd_search(context, chat_id, query, searching_msg, search_id=search_id)


# Editions of the same recording (album, compilation, reissue) differ by this much at most.
_SAME_EDITION_SECS = 2


def _collapse_editions(tracks: list[TrackInfo]) -> list[TrackInfo]:
    """Keep one entry per artist+title+length, preferring the earliest release.

    Spotify lists the same recording on the studio album, "Greatest Hits" and
    three reissues; the Soulseek search ignores the album anyway, so the picker
    only needs to show versions that actually differ (remix, live, edit).
    """
    kept: list[TrackInfo] = []
    for track in tracks:
        key = (track.artist.lower(), track.title.lower())
        twin = next(
            (
                k
                for k in kept
                if (k.artist.lower(), k.title.lower()) == key
                and abs(k.duration_secs - track.duration_secs) <= _SAME_EDITION_SECS
            ),
            None,
        )
        if twin is None:
            kept.append(track)
        elif track.year and (not twin.year or track.year < twin.year):
            kept[kept.index(twin)] = track
    return kept


def _filter_candidates(query: str, tracks: list[TrackInfo]) -> list[TrackInfo]:
    """Dedup Spotify results, collapse editions, and prefer candidates whose artist matches the query."""
    query = clean_query(query)
    query_lower = query.lower()
    query_words = set(query_lower.split())
    query_artist = ""
    if _has_separator(query):
        query_artist = parse_query_artist_title(query)[0].lower()

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

    return _collapse_editions(unique_tracks)


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
    # The picker message becomes the search card: one message per query, not two.
    await safe_query_edit(
        query,
        self.t(chat_id, "spotify_selected", track=track_md(track), duration=track.duration_display),
        parse_mode=ParseMode.MARKDOWN,
    )
    searching_msg = query.message
    if searching_msg is None or getattr(searching_msg, "message_id", None) is None:
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

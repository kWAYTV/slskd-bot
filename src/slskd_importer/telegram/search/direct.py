"""Metadata-free Soulseek search (no Spotify match available)."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.soulseek.query import parse_query_artist_title
from slskd_importer.soulseek.scoring import rank_responses
from slskd_importer.telegram.core.session import split_search_callback
from slskd_importer.telegram.search.results import present_search_results
from slskd_importer.telegram.ui.editing import safe_edit, safe_query_edit
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def handle_direct_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Handle 'Search Soulseek directly' button — search slskd with metadata parsed from the query."""
    query = update.callback_query
    parsed = split_search_callback(data)
    search_id = parsed[0] if parsed else ""
    pending = self.pending.get(search_id) if search_id else None
    if not pending:
        await safe_query_edit(query, self.t(chat_id, "search_expired"))
        return

    search_query = pending.query
    logger.info("chat=%s search=%s direct Soulseek search %r", chat_id, search_id, search_query)
    display_track = _synthetic_track(search_query, None)

    await safe_query_edit(
        query,
        self.t(
            chat_id,
            "direct_searching",
            query=escape_md(search_query),
            artist=escape_md(display_track.artist),
            title=escape_md(display_track.title),
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    searching_msg = query.message

    task = context.application.create_task(
        self._do_direct_slskd_search(
            context,
            chat_id,
            search_query,
            searching_msg,
            search_id=search_id,
            display_track=display_track,
        ),
        update=update,
    )
    self._track_task(chat_id, task)


def _synthetic_track(query: str, display_track: TrackInfo | None) -> TrackInfo:
    """A duration-free TrackInfo for direct searches (display metadata or parsed query)."""
    if display_track:
        return TrackInfo(
            artist=display_track.artist,
            title=display_track.title,
            album=display_track.album,
            duration_ms=0,
            spotify_url="",
            year=display_track.year,
        )

    artist, title = parse_query_artist_title(query)
    return TrackInfo(
        artist=artist,
        title=title,
        album="",
        duration_ms=0,
        spotify_url="",
        year="",
    )


async def do_direct_slskd_search(
    self,
    context,
    chat_id: int,
    query: str,
    searching_msg,
    generation: int | None = None,
    display_track: TrackInfo | None = None,
    search_id: str | None = None,
):
    """Search slskd without Spotify metadata. Duration scoring gives flat 15 points."""
    if generation is None:
        generation = self._chat_generation.get(chat_id, 0)
    try:
        raw_responses = await self.slskd.search(query, timeout_secs=self.config.search_timeout_secs)
        if self._is_stale(chat_id, generation) or self._search_cancelled(search_id):
            return

        synthetic_track = _synthetic_track(query, display_track)
        ranked, is_fallback = rank_responses(
            raw_responses, synthetic_track, self.scorer, quality_preference=self.quality_pref(chat_id)
        )

        if self._is_stale(chat_id, generation) or self._search_cancelled(search_id):
            return

        if not ranked:
            if search_id:
                self._session.drop_search(search_id)
            await safe_edit(
                searching_msg,
                self.t(chat_id, "direct_no_results", query=query),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if search_id is None:
            search_id = self._next_search_id()
        await present_search_results(
            self,
            context,
            chat_id,
            synthetic_track,
            ranked,
            is_fallback,
            searching_msg,
            query=query,
            search_id=search_id,
        )

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during direct search for: %s", query)
        await safe_edit(
            searching_msg,
            self.t(chat_id, "slskd_unreachable"),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception(f"Direct search failed for: {query}")
        await safe_edit(searching_msg, self.t(chat_id, "something_wrong"))

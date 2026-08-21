"""Metadata-free Soulseek search (no Spotify match available)."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.soulseek.errors import SlskdUnavailableError
from music_downloader.soulseek.query import parse_query_artist_title
from music_downloader.telegram.search.results import present_search_results
from music_downloader.telegram.ui.editing import safe_edit

logger = logging.getLogger(__name__)


async def handle_direct_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Handle 'Search Soulseek directly' button — asks for Artist - Title, then searches slskd."""
    query = update.callback_query

    pending = self.pending.get(chat_id)
    if not pending:
        await query.edit_message_text(_("Search expired. Send a new query."))
        return

    search_query = pending.query
    self._awaiting_direct_metadata[chat_id] = search_query

    await query.edit_message_text(
        _(
            "🎵 How should this track be saved?\n\n"
            "Send the name as: `Artist - Title`\n"
            "(This will be used for the filename and tags)"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


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
    self, context, chat_id: int, query: str, searching_msg, generation: int, display_track: TrackInfo | None = None
):
    """Search slskd without Spotify metadata. Duration scoring gives flat 15 points."""
    try:
        raw_responses = await self.slskd.search(query, timeout_secs=self.config.search_timeout_secs)
        if self._is_stale(chat_id, generation):
            return

        synthetic_track = _synthetic_track(query, display_track)
        ranked, is_fallback = self._rank_responses(
            raw_responses, synthetic_track, quality_preference=self.quality_pref(chat_id)
        )

        if self._is_stale(chat_id, generation):
            return

        if not ranked:
            await safe_edit(
                searching_msg,
                _("🔍 Direct search: `{query}`\n\nNo results found on Soulseek.").format(query=query),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await present_search_results(
            self, context, chat_id, synthetic_track, ranked, is_fallback, searching_msg, query=query
        )

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during direct search for: %s", query)
        await safe_edit(
            searching_msg,
            _("Cannot reach slskd. Check `SLSKD_HOST` and the API key."),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception(f"Direct search failed for: {query}")
        await safe_edit(searching_msg, _("Something went wrong. Please try again."))

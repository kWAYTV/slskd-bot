"""Soulseek search for a resolved catalog track, with tier progress feedback."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.soulseek.fallbacks import search_with_fallbacks as soulseek_search_with_fallbacks
from slskd_importer.telegram.search.results import present_search_results
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.formatting import track_md
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def notify_if_already_owned(self, context, chat_id: int, track: TrackInfo) -> None:
    """Send a non-blocking heads-up when the track already exists in the library."""
    exact = await asyncio.to_thread(self.processor.find_exact, track.artist, track.title)
    history_hit = await asyncio.to_thread(
        self.history_repo.find_success,
        track.artist,
        track.title,
        track.spotify_url,
    )
    if not exact and not history_hit:
        return

    lines = [self.t(chat_id, "already_owned", track=track_md(track))]
    if exact:
        lines.append("\n".join(f"• `{f}`" for f in exact[:5]))
    if history_hit:
        lines.append(self.t(chat_id, "already_owned_saved", filename=history_hit.filename))
    lines.append(self.t(chat_id, "already_owned_anyway"))
    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def search_with_fallbacks(self, track: TrackInfo, chat_id: int, generation: int, on_tier=None, search_id=None):
    """Four-tier slskd search: full query, title-only, keyword+year, artist+latin keywords."""
    return await soulseek_search_with_fallbacks(
        self.slskd,
        self.scorer,
        track,
        timeout_secs=self.config.search_timeout_secs,
        is_cancelled=lambda: self._is_stale(chat_id, generation) or self._search_cancelled(search_id),
        on_tier=on_tier,
    )


async def do_slskd_search(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    searching_msg,
    generation: int | None = None,
    search_id: str | None = None,
):
    """Search slskd for a resolved Spotify track."""
    if generation is None:
        generation = self._chat_generation.get(chat_id, 0)
    if search_id is None:
        from slskd_importer.telegram.core.session import PendingSearch

        search_id = self._next_search_id()
        self.pending[search_id] = PendingSearch(
            query=f"{track.artist} {track.title}",
            track=track,
            chat_id=chat_id,
            search_id=search_id,
        )

    try:
        header = track_md(track)
        if self._is_stale(chat_id, generation) or self._search_cancelled(search_id):
            return

        await notify_if_already_owned(self, context, chat_id, track)
        if self._is_stale(chat_id, generation) or self._search_cancelled(search_id):
            return

        await safe_edit(
            searching_msg,
            self.t(
                chat_id,
                "searching_header",
                track=header,
                album=escape_md(track.album),
                year=escape_md(track.year),
                duration=track.duration_display,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        async def on_tier(kind: str):
            messages = {
                "title-only": self.t(chat_id, "searching_title_only", track=header),
                "keywords": self.t(chat_id, "searching_keywords", track=header),
                "artist-keywords": self.t(chat_id, "searching_artist_kw", track=header),
            }
            await safe_edit(searching_msg, messages[kind], parse_mode=ParseMode.MARKDOWN)

        ranked, is_fallback, stale = await search_with_fallbacks(
            self, track, chat_id, generation, on_tier=on_tier, search_id=search_id
        )
        if stale:
            logger.info("chat=%s search=%s cancelled for %s - %s", chat_id, search_id, track.artist, track.title)
            return

        logger.info(
            "chat=%s search=%s slskd ranked %d result(s) fallback=%s for %s - %s",
            chat_id,
            search_id,
            len(ranked),
            is_fallback,
            track.artist,
            track.title,
        )
        if not ranked:
            self._session.drop_search(search_id)
            await safe_edit(
                searching_msg,
                self.t(chat_id, "no_soulseek", track=header, duration=track.duration_display),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await present_search_results(
            self,
            context,
            chat_id,
            track,
            ranked,
            is_fallback,
            searching_msg,
            query=f"{track.artist} {track.title}",
            search_id=search_id,
        )

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during search for: %s - %s", track.artist, track.title)
        if search_id:
            self._session.drop_search(search_id)
        await safe_edit(
            searching_msg,
            self.t(chat_id, "slskd_unreachable"),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception(f"Unexpected error in _do_slskd_search for: {track.artist} - {track.title}")
        if search_id:
            self._session.drop_search(search_id)
        await safe_edit(
            searching_msg,
            self.t(chat_id, "search_error"),
        )

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
    exact = self.processor.find_exact(track.artist, track.title)
    history_hit = await asyncio.to_thread(
        self.history_repo.find_success,
        track.artist,
        track.title,
        track.spotify_url,
    )
    if not exact and not history_hit:
        return

    lines = [f"⚠️ *Already in the library:* {track_md(track)}"]
    if exact:
        lines.append("\n".join(f"• `{f}`" for f in exact[:5]))
    if history_hit:
        lines.append(f"Previously saved as `{history_hit.filename}`")
    lines.append("Searching anyway — pick a result below or ignore.")
    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def search_with_fallbacks(self, track: TrackInfo, chat_id: int, generation: int, on_tier=None):
    """Four-tier slskd search: full query, title-only, keyword+year, artist+latin keywords."""
    return await soulseek_search_with_fallbacks(
        self.slskd,
        self.scorer,
        track,
        timeout_secs=self.config.search_timeout_secs,
        quality_preference=self.quality_pref(chat_id),
        is_cancelled=lambda: self._is_stale(chat_id, generation),
        on_tier=on_tier,
    )


async def do_slskd_search(self, context, chat_id: int, track: TrackInfo, searching_msg, generation: int):
    """Search slskd for a resolved Spotify track."""
    try:
        header = track_md(track)
        await notify_if_already_owned(self, context, chat_id, track)

        await safe_edit(
            searching_msg,
            (
                f"🎵 {header}\nAlbum: {escape_md(track.album)} ({escape_md(track.year)})\nDuration: {track.duration_display}\n\nSearching slskd..."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        async def on_tier(kind: str):
            messages = {
                "title-only": (f"🎵 {header}\n\nNo results with full query — retrying with song title only…"),
                "keywords": (f"🎵 {header}\n\nStill no results — trying keyword variations with year…"),
                "artist-keywords": (f"🎵 {header}\n\nStill no results — trying artist + keyword search…"),
            }
            await safe_edit(searching_msg, messages[kind], parse_mode=ParseMode.MARKDOWN)

        ranked, is_fallback, stale = await search_with_fallbacks(self, track, chat_id, generation, on_tier=on_tier)
        if stale:
            logger.info("chat=%s search cancelled (stale) for %s - %s", chat_id, track.artist, track.title)
            return

        logger.info(
            "chat=%s slskd ranked %d result(s) fallback=%s for %s - %s",
            chat_id,
            len(ranked),
            is_fallback,
            track.artist,
            track.title,
        )
        if not ranked:
            await safe_edit(
                searching_msg,
                (
                    f"🎵 {header} ({track.duration_display})\n\n"
                    "No results found on Soulseek matching this track.\n"
                    "Try a different search query."
                ),
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
        )

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during search for: %s - %s", track.artist, track.title)
        self.pending.pop(chat_id, None)
        await safe_edit(
            searching_msg,
            ("Cannot reach slskd. Check `SLSKD_HOST` and the API key."),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception(f"Unexpected error in _do_slskd_search for: {track.artist} - {track.title}")
        self.pending.pop(chat_id, None)
        await safe_edit(
            searching_msg,
            ("Something went wrong during the search. Please try again."),
        )

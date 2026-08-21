"""Pasted Spotify/SoundCloud track links — resolve metadata, then search Soulseek."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.catalog.links import extract_soundcloud_url, extract_spotify_track_id
from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.soundcloud import matches_spotify_candidate
from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def handle_link_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query: str) -> bool:
    """Handle pasted Spotify/SoundCloud links. Returns True when the message was a link."""
    if PlaylistResolver.is_spotify_url(query):
        await update.message.reply_text(
            _("That looks like a playlist or album link.\nUse `/import {url}` to import it.").format(
                url=query.split()[0]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    spotify_track_id = extract_spotify_track_id(query)
    if spotify_track_id:
        await _search_from_spotify_link(self, update, context, chat_id, spotify_track_id)
        return True

    soundcloud_url = extract_soundcloud_url(query)
    if soundcloud_url:
        await _search_from_soundcloud_link(self, update, context, chat_id, soundcloud_url)
        return True

    return False


async def _search_from_spotify_link(self, update, context, chat_id: int, track_id: str):
    """Resolve a pasted Spotify track link directly (no search ambiguity) and hit Soulseek."""
    await self._cancel_chat_operations(chat_id)
    generation = self._chat_generation[chat_id]

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("🔗 Resolving Spotify track link..."),
    )

    track = await asyncio.to_thread(self.spotify.get_track, track_id)
    if self._is_stale(chat_id, generation):
        return
    if not track:
        await safe_edit(searching_msg, _("Could not resolve that Spotify track link. Try the song name instead."))
        return

    self.pending[chat_id] = PendingSearch(
        query=f"{track.artist} {track.title}",
        track=track,
        user_id=update.effective_user.id,
    )
    await self._do_slskd_search(context, chat_id, track, searching_msg, generation)


async def _search_from_soundcloud_link(self, update, context, chat_id: int, url: str):
    """Resolve a SoundCloud link, enrich via a *verified* Spotify match, or search directly.

    The Spotify match is verified against the SoundCloud title so a track that
    isn't on Spotify (common for fresh SoundCloud releases) can't be silently
    replaced by a different song from the same artist.
    """
    await self._cancel_chat_operations(chat_id)
    generation = self._chat_generation[chat_id]

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("🔗 Resolving SoundCloud link..."),
    )

    sc_track = await asyncio.to_thread(self.soundcloud.resolve, url)
    if self._is_stale(chat_id, generation):
        return
    if not sc_track:
        await safe_edit(searching_msg, _("Could not resolve that SoundCloud link. Try the song name instead."))
        return

    await safe_edit(
        searching_msg,
        _("🎧 SoundCloud: *{artist} - {title}*\nLooking it up...").format(
            artist=escape_md(sc_track.artist), title=escape_md(sc_track.title)
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    candidates = await asyncio.to_thread(self.spotify.search_multiple, sc_track.query, 10)
    if self._is_stale(chat_id, generation):
        return
    verified = next(
        (c for c in candidates if matches_spotify_candidate(sc_track, c.artist, c.title)),
        None,
    )

    if verified:
        self.pending[chat_id] = PendingSearch(
            query=sc_track.query,
            track=verified,
            user_id=update.effective_user.id,
        )
        await self._do_slskd_search(context, chat_id, verified, searching_msg, generation)
        return

    # Not on Spotify — search Soulseek directly, saving under the SoundCloud name.
    synthetic_track = TrackInfo(
        artist=sc_track.artist,
        title=sc_track.title,
        album="",
        duration_ms=0,
        spotify_url="",
        year="",
    )
    self.pending[chat_id] = PendingSearch(
        query=sc_track.query,
        track=None,
        user_id=update.effective_user.id,
    )
    await safe_edit(
        searching_msg,
        _("🎧 SoundCloud: *{artist} - {title}*\nNot on Spotify — searching Soulseek directly...").format(
            artist=escape_md(sc_track.artist), title=escape_md(sc_track.title)
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    direct_query = f"{sc_track.artist} {sc_track.title}".strip()
    await self._do_direct_slskd_search(
        context, chat_id, direct_query, searching_msg, generation, display_track=synthetic_track
    )

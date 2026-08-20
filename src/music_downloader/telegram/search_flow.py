"""Single-track search conversation: catalog lookup, Soulseek search, result pick."""

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
from music_downloader.soulseek.errors import SlskdUnavailableError
from music_downloader.soulseek.fallbacks import search_with_fallbacks as soulseek_search_with_fallbacks
from music_downloader.soulseek.query import parse_query_artist_title
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.keyboards import (
    build_direct_search_keyboard,
    build_duplicate_keyboard,
    build_results_keyboard,
    build_spotify_keyboard,
)
from music_downloader.telegram.messages import escape_md, format_result_reasons, md_code_safe, safe_edit
from music_downloader.telegram.session import PendingSearch

logger = logging.getLogger(__name__)


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — treat as song search queries."""
    if not await self._check_auth(update):
        return

    query = update.message.text.strip()
    if not query:
        return

    chat_id = update.effective_chat.id

    if chat_id in self._awaiting_direct_metadata:
        search_query = self._awaiting_direct_metadata.pop(chat_id)
        generation = self._chat_generation.get(chat_id, 0)

        if " - " in query:
            artist, title = query.split(" - ", 1)
        else:
            artist, title = query, search_query

        synthetic_track = TrackInfo(
            artist=artist.strip(),
            title=title.strip(),
            album="",
            duration_ms=0,
            spotify_url="",
            year="",
        )

        self.pending[chat_id] = PendingSearch(
            query=search_query,
            track=None,
            user_id=update.effective_user.id,
        )

        searching_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=_("🔍 Searching slskd for: `{query}`\nSaving as: *{artist} - {title}*").format(
                query=search_query,
                artist=escape_md(synthetic_track.artist),
                title=escape_md(synthetic_track.title),
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        await self._do_direct_slskd_search(
            context, chat_id, search_query, searching_msg, generation, display_track=synthetic_track
        )
        return

    if await _handle_link_query(self, update, context, chat_id, query):
        return

    await self._cancel_chat_operations(chat_id)
    generation = self._chat_generation[chat_id]

    similar = self.processor.find_similar(query)
    if similar:
        existing_list = "\n".join(f"• `{f}`" for f in similar[:5])
        await update.message.reply_text(
            _("⚠️ *Similar files already in library:*\n\n{files}\n\nContinue searching anyway?").format(
                files=existing_list
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_duplicate_keyboard(),
        )
        self.pending[chat_id] = PendingSearch(query=query, track=None, user_id=update.effective_user.id)
        return

    await self._do_search(update, context, query, generation)


async def _handle_link_query(
    self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query: str
) -> bool:
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


async def do_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, generation: int):
    """Resolve metadata via Spotify, then proceed to slskd search."""
    chat_id = update.effective_chat.id

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("🔍 Looking up: `{query}`").format(query=query),
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        tracks = self.spotify.search_multiple(query, limit=50)
        if self._is_stale(chat_id, generation):
            return

        if not tracks:
            await safe_edit(
                searching_msg,
                _("Could not find `{query}` on Spotify.\nYou can search Soulseek directly instead.").format(
                    query=query
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_direct_search_keyboard(),
            )
            self.pending[chat_id] = PendingSearch(query=query, track=None, user_id=update.effective_user.id)
            return

        query_lower = query.lower()
        query_words = set(query_lower.split())
        query_artist = ""
        if " - " in query:
            query_artist = query.split(" - ", 1)[0].strip().lower()

        seen = set()
        unique_tracks = []
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
            seen = set()
            for t in tracks:
                key = (t.artist.lower(), t.title.lower(), t.album.lower())
                if key not in seen:
                    seen.add(key)
                    unique_tracks.append(t)

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
            self._format_spotify_results(unique_tracks, page=0),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=build_spotify_keyboard(unique_tracks, page=0),
        )

    except Exception:
        logger.exception(f"Unexpected error in _do_search for: {query}")
        self._spotify_candidates.pop(chat_id, None)
        self._spotify_page.pop(chat_id, None)
        await safe_edit(searching_msg, _("Something went wrong. Please try again."))


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


async def do_slskd_search(
    self, context, chat_id: int, track: TrackInfo, searching_msg, generation: int, skip_library_check: bool = False
):
    """Search slskd for a resolved Spotify track."""
    try:
        header = _track_md(track)
        if not skip_library_check:
            blocked = await _prompt_if_already_owned(self, context, chat_id, track, searching_msg)
            if blocked:
                return

        await safe_edit(
            searching_msg,
            _("🎵 {track}\nAlbum: {album} ({year})\nDuration: {duration}\n\nSearching slskd...").format(
                track=header,
                album=escape_md(track.album),
                year=escape_md(track.year),
                duration=track.duration_display,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        async def on_tier(kind: str):
            messages = {
                "title-only": _("🎵 {track}\n\nNo results with full query — retrying with song title only…").format(
                    track=header
                ),
                "keywords": _("🎵 {track}\n\nStill no results — trying keyword variations with year…").format(
                    track=header
                ),
                "artist-keywords": _("🎵 {track}\n\nStill no results — trying artist + keyword search…").format(
                    track=header
                ),
            }
            await safe_edit(searching_msg, messages[kind], parse_mode=ParseMode.MARKDOWN)

        ranked, is_fallback, stale = await search_with_fallbacks(self, track, chat_id, generation, on_tier=on_tier)
        if stale:
            return

        if not ranked:
            await safe_edit(
                searching_msg,
                _(
                    "🎵 {track} ({duration})\n\n"
                    "No results found on Soulseek matching this track.\n"
                    "Try a different search query."
                ).format(track=header, duration=track.duration_display),
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
            _("Cannot reach slskd. Check `SLSKD_HOST` and the API key."),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception(f"Unexpected error in _do_slskd_search for: {track.artist} - {track.title}")
        self.pending.pop(chat_id, None)
        await safe_edit(
            searching_msg,
            _("Something went wrong during the search. Please try again."),
        )


async def handle_duplicate_response(self, update, context, chat_id: int, data: str):
    """Handle Continue/Cancel response to duplicate detection."""
    query = update.callback_query
    action = data.split(":", 1)[1]

    pending = self.pending.pop(chat_id, None)

    if action == "cancel" or not pending:
        await query.edit_message_text(_("Cancelled."))
        return

    await query.edit_message_text(
        _("Continuing with search: `{query}`").format(query=pending.query),
        parse_mode=ParseMode.MARKDOWN,
    )
    generation = self._chat_generation.get(chat_id, 0)
    if pending.track:
        # Keep the pending entry so user_id survives into the results/download flow.
        pending.user_id = pending.user_id or query.from_user.id
        self.pending[chat_id] = pending
        searching_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=_("🔍 Searching slskd for FLAC..."),
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._do_slskd_search(context, chat_id, pending.track, searching_msg, generation, skip_library_check=True)
        return
    await self._do_search(update, context, pending.query, generation)


async def handle_spotify_page(self, update, context, chat_id: int, data: str):
    """Handle Spotify page navigation (◀️ / ▶️)."""
    query = update.callback_query
    candidates = self._spotify_candidates.get(chat_id)
    if not candidates:
        await query.edit_message_text(_("Search expired. Send a new query."))
        return

    try:
        page = int(data.split(":", 1)[1])
    except ValueError:
        return

    self._spotify_page[chat_id] = page
    await query.edit_message_text(
        self._format_spotify_results(candidates, page=page),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=build_spotify_keyboard(candidates, page=page),
    )


async def handle_spotify_selection(self, update, context, chat_id: int, data: str):
    """Handle Spotify track selection from multiple results."""
    query = update.callback_query
    action = data.split(":", 1)[1]

    candidates = self._spotify_candidates.pop(chat_id, None)
    self._spotify_page.pop(chat_id, None)

    if action == "cancel" or not candidates:
        await query.edit_message_text(_("Cancelled."))
        return

    try:
        index = int(action)
    except ValueError:
        return

    if index >= len(candidates):
        return

    track = candidates[index]
    await query.edit_message_text(
        _("Selected: {track} ({duration})").format(track=_track_md(track), duration=track.duration_display),
        parse_mode=ParseMode.MARKDOWN,
    )

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("🔍 Searching slskd for FLAC..."),
        parse_mode=ParseMode.MARKDOWN,
    )
    generation = self._chat_generation.get(chat_id, 0)
    await self._do_slskd_search(context, chat_id, track, searching_msg, generation)


async def handle_results_page(self, update, context, chat_id: int, data: str):
    """Handle slskd results page navigation (◀️ / ▶️)."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending or not pending.track:
        await query.edit_message_text(_("Search expired. Send a new query."))
        return

    try:
        page = int(data.split(":", 1)[1])
    except ValueError:
        return

    pending.page = page
    results_text = self._format_results(
        pending.track,
        pending.results,
        pending.is_fallback,
        page=page,
        page_size=self.config.max_results,
    )
    await query.edit_message_text(
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(pending.results, page=page, page_size=self.config.max_results),
    )


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


async def do_direct_slskd_search(
    self, context, chat_id: int, query: str, searching_msg, generation: int, display_track: TrackInfo | None = None
):
    """Search slskd without Spotify metadata. Duration scoring gives flat 15 points."""
    try:
        raw_responses = await self.slskd.search(query, timeout_secs=self.config.search_timeout_secs)
        if self._is_stale(chat_id, generation):
            return

        if display_track:
            synthetic_track = TrackInfo(
                artist=display_track.artist,
                title=display_track.title,
                album=display_track.album,
                duration_ms=0,
                spotify_url="",
                year=display_track.year,
            )
        else:
            artist, title = parse_query_artist_title(query)
            synthetic_track = TrackInfo(
                artist=artist,
                title=title,
                album="",
                duration_ms=0,
                spotify_url="",
                year="",
            )

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


def _track_md(track: TrackInfo) -> str:
    return f"*{escape_md(track.artist)} - {escape_md(track.title)}*"


async def _prompt_if_already_owned(self, context, chat_id: int, track: TrackInfo, searching_msg) -> bool:
    """Return True if we paused for a duplicate confirmation."""
    exact = self.processor.find_exact(track.artist, track.title)
    history_hit = await asyncio.to_thread(
        self.history_repo.find_success,
        track.artist,
        track.title,
        track.spotify_url,
    )
    if not exact and not history_hit:
        return False

    lines = [_("⚠️ *Already in the library:* {track}").format(track=_track_md(track)) + "\n"]
    if exact:
        lines.append(_("On disk:") + "\n" + "\n".join(f"• `{f}`" for f in exact[:5]))
    if history_hit:
        lines.append(_("Previously saved as `{filename}`").format(filename=history_hit.filename))
    lines.append("\n" + _("Search Soulseek anyway?"))
    user_id = None
    existing = self.pending.get(chat_id)
    if existing:
        user_id = existing.user_id
    self.pending[chat_id] = PendingSearch(
        query=f"{track.artist} {track.title}",
        track=track,
        user_id=user_id,
        skip_library_check=True,
    )
    await safe_edit(
        searching_msg,
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_duplicate_keyboard(),
    )
    return True


async def present_search_results(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    ranked: list[SearchResult],
    is_fallback: bool,
    searching_msg,
    query: str,
):
    """Store ranked results and either auto-download or show the pick keyboard."""
    existing = self.pending.get(chat_id)
    self.pending[chat_id] = PendingSearch(
        query=query,
        track=track,
        results=ranked,
        message_id=searching_msg.message_id,
        is_fallback=is_fallback,
        user_id=existing.user_id if existing else None,
    )

    if self.is_auto(chat_id):
        header = _track_md(track)
        await safe_edit(
            searching_msg,
            _("⚡ Auto-downloading best match for {track}...").format(track=header),
            parse_mode=ParseMode.MARKDOWN,
        )
        result = ranked[0]
        text = _("⬇️ *Downloading #{n}...*\n{track}\nFrom: `{user}`\nFile: `{file}`").format(
            n=1, track=header, user=md_code_safe(result.username), file=md_code_safe(result.basename)
        )
        reasons = format_result_reasons(track, result)
        if reasons:
            text += f"\n{reasons}"
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        user_id = self.pending[chat_id].user_id if chat_id in self.pending else None
        task = context.application.create_task(
            self._do_download(context, chat_id, track, result, status_msg, 0, user_id=user_id),
        )
        self._track_task(chat_id, task)
        return

    results_text = self._format_results(track, ranked, is_fallback, page=0, page_size=self.config.max_results)
    await safe_edit(
        searching_msg,
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(ranked, page=0, page_size=self.config.max_results),
    )

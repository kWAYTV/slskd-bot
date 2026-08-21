"""Free-text message entry point — song queries, link detection, duplicates."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.search.links import handle_link_query
from music_downloader.telegram.ui.keyboards import build_duplicate_keyboard
from music_downloader.telegram.ui.markdown import escape_md


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — treat as song search queries."""
    if not await self._check_auth(update):
        return

    query = update.message.text.strip()
    if not query:
        return

    chat_id = update.effective_chat.id

    if chat_id in self._awaiting_direct_metadata:
        await _run_direct_search_with_metadata(self, update, context, chat_id, query)
        return

    if await handle_link_query(self, update, context, chat_id, query):
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


def _split_artist_title(query: str, fallback_title: str) -> tuple[str, str]:
    """Split an 'Artist - Title' answer; a bare answer is the artist, keep the search as title."""
    if " - " not in query:
        return query.strip(), fallback_title.strip()
    artist, title = query.split(" - ", 1)
    return artist.strip(), title.strip()


async def _run_direct_search_with_metadata(self, update, context, chat_id: int, query: str):
    """The user answered the 'Artist - Title' prompt for a direct Soulseek search."""
    search_query = self._awaiting_direct_metadata.pop(chat_id)
    generation = self._chat_generation.get(chat_id, 0)

    artist, title = _split_artist_title(query, fallback_title=search_query)
    synthetic_track = TrackInfo(
        artist=artist,
        title=title,
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

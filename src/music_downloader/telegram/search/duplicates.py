"""Already-in-library detection and the Continue/Cancel confirmation."""

from __future__ import annotations

import asyncio

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.formatting import track_md
from music_downloader.telegram.ui.keyboards import build_duplicate_keyboard


async def prompt_if_already_owned(self, context, chat_id: int, track: TrackInfo, searching_msg) -> bool:
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

    lines = [(f"⚠️ *Already in the library:* {track_md(track)}") + "\n"]
    if exact:
        lines.append(("On disk:") + "\n" + "\n".join(f"• `{f}`" for f in exact[:5]))
    if history_hit:
        lines.append(f"Previously saved as `{history_hit.filename}`")
    lines.append("\n" + ("Search Soulseek anyway?"))
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


async def handle_duplicate_response(self, update, context, chat_id: int, data: str):
    """Handle Continue/Cancel response to duplicate detection."""
    query = update.callback_query
    action = data.split(":", 1)[1]

    pending = self.pending.pop(chat_id, None)

    if action == "cancel" or not pending:
        await query.edit_message_text("Cancelled.")
        return

    await query.edit_message_text(
        (f"Continuing with search: `{pending.query}`"),
        parse_mode=ParseMode.MARKDOWN,
    )
    generation = self._chat_generation.get(chat_id, 0)
    if pending.track:
        # Keep the pending entry so user_id survives into the results/download flow.
        pending.user_id = pending.user_id or query.from_user.id
        self.pending[chat_id] = pending
        searching_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=("🔍 Searching slskd for FLAC..."),
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._do_slskd_search(context, chat_id, pending.track, searching_msg, generation, skip_library_check=True)
        return
    await self._do_search(update, context, pending.query, generation)

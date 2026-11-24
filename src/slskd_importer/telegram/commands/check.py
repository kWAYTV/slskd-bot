"""/check: are the recently saved tracks the songs that were asked for?"""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.lookup import has_separator, track_from_text
from slskd_importer.catalog.names import normalize, same_artist, same_title
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.batch import Item, ItemStatus
from slskd_importer.queue.confidence import names_the_song
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.ui.markdown import code_span

RECENT_BATCHES = 10
MAX_LINES = 25


def asked_for(item: Item) -> TrackInfo | None:
    """The song as the requester wrote it, when the text names artist and title."""
    return track_from_text(item.query) if has_separator(item.query) else item.track


def doubt(item: Item, remote_path: str) -> bool:
    """True when a saved track may not be the requested song.

    Either its identity drifted from the text (another artist or title), or the
    file it came from does not carry the song's name.
    """
    asked, got = asked_for(item), item.track
    if asked is None or got is None:
        return False
    drifted = not (
        same_artist(normalize(asked.artist), normalize(got.artist))
        and same_title(normalize(asked.title), normalize(got.title))
    )
    misnamed = bool(remote_path) and not names_the_song(asked, SearchResult("", remote_path, 0))
    return drifted or misnamed


async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return
    chat_id = update.effective_chat.id
    saved, doubtful = await asyncio.to_thread(_review_recent, self, chat_id)
    if not doubtful:
        await update.message.reply_text(self.t(chat_id, "check_clean", n=saved))
        return

    lines = [self.t(chat_id, "check_header", n=len(doubtful), total=saved), ""]
    for item, source in doubtful[:MAX_LINES]:
        lines.append(
            self.t(
                chat_id,
                "check_line",
                asked=code_span(item.query),
                saved=code_span(item.saved_name),
                source=code_span(source or "?"),
            )
        )
    if len(doubtful) > MAX_LINES:
        lines.append(f"… +{len(doubtful) - MAX_LINES}")
    lines += ["", self.t(chat_id, "check_hint")]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def _review_recent(self, chat_id: int) -> tuple[int, list[tuple[Item, str]]]:
    """(saved tracks looked at, the doubtful ones with the remote file name they came from). Blocking."""
    saved = 0
    doubtful: list[tuple[Item, str]] = []
    for batch in self.queue_store.recent_batches(chat_id, RECENT_BATCHES):
        for item in self.queue_store.items(batch.id):
            if item.status != ItemStatus.done or not item.saved_name:
                continue
            saved += 1
            record = self.history_repo.get_for_chat(item.history_id, chat_id) if item.history_id else None
            remote_path = record.remote_path if record else ""
            if doubt(item, remote_path):
                doubtful.append((item, remote_path.replace("\\", "/").rsplit("/", 1)[-1]))
    return saved, doubtful

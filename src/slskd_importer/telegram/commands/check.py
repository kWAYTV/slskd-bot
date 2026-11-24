"""/check: are the recently saved tracks the songs that were asked for? Remove the wrong ones with a tap."""

from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.lookup import has_separator, track_from_text
from slskd_importer.catalog.names import normalize, same_artist, same_title
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.batch import Item, ItemStatus
from slskd_importer.queue.confidence import names_the_song
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.formatting import clip
from slskd_importer.telegram.ui.markdown import code_span

logger = logging.getLogger(__name__)

RECENT_BATCHES = 10
MAX_LINES = 20
# Callback data of a remove button: ``cu:<item id>``.
UNDO_PREFIX = "cu"


def asked_for(item: Item) -> TrackInfo | None:
    """The song as the requester wrote it, when the text names artist and title."""
    return track_from_text(item.query) if has_separator(item.query) else item.track


def doubt(item: Item, remote_path: str) -> bool:
    """True when a saved track may not be the requested song.

    Either its identity drifted from the text (another artist or title), or the
    path it came from (folders included) does not carry the song's name.
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


def source_label(remote_path: str) -> str:
    """The folder and file a track came from: ``Album/01. Title.flac``."""
    parts = [part for part in remote_path.replace("\\", "/").split("/") if part]
    return "/".join(parts[-2:]) or "?"


async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return
    chat_id = update.effective_chat.id
    text, markup = await asyncio.to_thread(_report, self, chat_id)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)


async def handle_check_undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """A remove button under /check: take that track out of the library and redraw the report."""
    query = update.callback_query
    if not self._can_save_library(query.from_user.id):
        return
    try:
        item_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    item = await asyncio.to_thread(self.queue_store.get_item, item_id)
    batch = await asyncio.to_thread(self.queue_store.get_batch_for_chat, item.batch_id, chat_id) if item else None
    if batch is not None and item.status == ItemStatus.done and batch.to_library:
        await asyncio.to_thread(self.shelf.remove, item.saved_name, item.history_id)
        await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.removed)
        logger.info("chat=%s /check removed %s", chat_id, item.saved_name)
        self.cards.request(batch.id)
    text, markup = await asyncio.to_thread(_report, self, chat_id)
    await safe_query_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)


def _report(self, chat_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """The /check message: the doubtful tracks, each with a remove button. Blocking."""
    saved, doubtful = _review_recent(self, chat_id)
    if not doubtful:
        return self.t(chat_id, "check_clean", n=saved), None

    shown = doubtful[:MAX_LINES]
    lines = [self.t(chat_id, "check_header", n=len(doubtful), total=saved), ""]
    for item, remote_path in shown:
        lines.append(
            self.t(
                chat_id,
                "check_line",
                asked=code_span(item.query),
                saved=code_span(item.saved_name),
                source=code_span(source_label(remote_path)),
            )
        )
    if len(doubtful) > MAX_LINES:
        lines.append(f"… +{len(doubtful) - MAX_LINES}")
    lines += ["", self.t(chat_id, "check_hint")]
    buttons = [
        [InlineKeyboardButton(clip(f"🗑  {item.query}"), callback_data=f"{UNDO_PREFIX}:{item.id}")] for item, _ in shown
    ]
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def _review_recent(self, chat_id: int) -> tuple[int, list[tuple[Item, str]]]:
    """(saved tracks looked at, the doubtful ones with the remote path they came from). Blocking."""
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
                doubtful.append((item, remote_path))
    return saved, doubtful

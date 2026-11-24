"""One track on a card: what happened to it and what can be done next."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue import progress as phases
from slskd_importer.queue.batch import Batch, Item, ItemStatus
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.status import Translate, item_icon
from slskd_importer.telegram.ui.formatting import progress_bar
from slskd_importer.telegram.ui.markdown import code_span, escape_md

Card = tuple[str, InlineKeyboardMarkup | None]


def render_item(t: Translate, batch: Batch, item: Item, progress: Progress | None, *, alone: bool) -> Card:
    """*alone*: the batch is this one track, so the card offers Cancel instead of Back."""
    track = item.track
    head = f"{item_icon(item, progress)}  *{escape_md(item.label)}*"
    if track is not None and track.duration_ms:
        head += f"  ·  {track.duration_display}"
    lines = [head, *_body(t, batch, item, progress)]
    return "\n".join(lines), _keyboard(t, batch, item, alone=alone)


def _body(t: Translate, batch: Batch, item: Item, progress: Progress | None) -> list[str]:
    status = item.status
    if status == ItemStatus.pending:
        return [t("item_pending")]
    if status == ItemStatus.working:
        return _working(t, progress)
    if status == ItemStatus.done:
        first = t("item_saved", name=code_span(item.saved_name)) if batch.to_library else t("item_sent")
        return [first, *(escape_md(line) for line in (item.quality, item.detail) if line)]
    if status == ItemStatus.owned:
        return [t("item_owned"), code_span(item.saved_name)]
    lines = [t(f"item_{status}")]
    if item.detail and status in (ItemStatus.review, ItemStatus.failed):
        lines.append(escape_md(item.detail))
    return lines


def _working(t: Translate, progress: Progress | None) -> list[str]:
    if progress is None:
        return [t("item_pending")]
    if progress.phase != phases.DOWNLOADING:
        return [t(f"item_{progress.phase}")]
    if progress.queued:
        return [t("item_queued_peer")]
    percent = progress.percent or 0.0
    return [f"{t('item_downloading')}  {percent:.0f}%", progress_bar(percent)]


def _keyboard(t: Translate, batch: Batch, item: Item, *, alone: bool) -> InlineKeyboardMarkup | None:
    def button(label_key: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(t(label_key), callback_data=actions.encode(action, batch.id, item.id))

    status = item.status
    row: list[InlineKeyboardButton] = []
    if status == ItemStatus.done:
        row.append(button("btn_other_versions", actions.PICKER))
        if batch.to_library:
            row += [button("btn_undo", actions.UNDO), button("btn_send_file", actions.SEND)]
    elif status == ItemStatus.owned:
        row.append(button("btn_anyway", actions.AGAIN))
    elif status == ItemStatus.review:
        row.append(button("btn_choose", actions.PICKER))
    elif status == ItemStatus.no_match:
        row.append(button("btn_search_again", actions.RETRY))
    elif status == ItemStatus.failed:
        row += [button("btn_retry", actions.RETRY), button("btn_choose", actions.PICKER)]
    elif status in (ItemStatus.removed, ItemStatus.cancelled):
        row.append(button("btn_again", actions.AGAIN))
    elif alone:
        row.append(button("btn_cancel", actions.CANCEL))

    rows = [row] if row else []
    if not alone:
        rows.append([InlineKeyboardButton(t("btn_back"), callback_data=actions.encode(actions.LIST, batch.id))])
    return InlineKeyboardMarkup(rows) if rows else None

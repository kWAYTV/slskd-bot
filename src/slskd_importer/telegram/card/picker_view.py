"""The Soulseek copies found for one track, for choosing one by hand."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue.batch import WAITING_STATUSES, Batch, Item, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.queue.pick import decode_pick
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.copy_token import copy_number
from slskd_importer.telegram.card.item_view import Card
from slskd_importer.telegram.card.status import Translate, identity_lines
from slskd_importer.telegram.ui.markdown import bold, code_span


def render_picker(
    t: Translate,
    batch: Batch,
    item: Item,
    copies: Copies | None,
    page: int,
    page_size: int,
    *,
    back: str = "",
    remaining: int = 0,
) -> Card:
    """*copies* None means the search is still running.

    *back*: callback data of Back (the item view by default). *remaining*: tracks
    still waiting for a pick, shown while going through them one after another.
    """
    last_row = [
        InlineKeyboardButton(t("btn_back"), callback_data=back or actions.encode(actions.ITEM, batch.id, item.id))
    ]
    if item.status in WAITING_STATUSES:
        last_row.append(
            InlineKeyboardButton(t("btn_skip"), callback_data=actions.encode(actions.SKIP, batch.id, item.id))
        )

    track = item.track
    head = bold(item.label)
    if track is not None and track.duration_ms:
        head += f"  ·  {track.duration_display}"
    lines = [head, *identity_lines(t, item)]
    if remaining:
        lines.append(t("picker_remaining", n=remaining))
    if copies is None:
        return "\n".join([*lines, t("picker_searching")]), InlineKeyboardMarkup([last_row])
    if not copies.ranked:
        return "\n".join([*lines, t("item_no_match")]), InlineKeyboardMarkup([last_row])

    ranked = copies.ranked
    pages = max(1, -(-len(ranked) // page_size))
    page = max(0, min(page, pages - 1))
    start = page * page_size
    shown = list(enumerate(ranked[start : start + page_size], start=start))
    # The copy picked before, when it is the one that failed: worth knowing before picking it again.
    failed = decode_pick(item.pick) if item.status == ItemStatus.failed else None

    lines += [t("picker_lossy" if copies.lossy else "picker_choose", total=len(ranked)), ""]
    lines += [_copy_line(t, index, copy, failed=copy == failed) for index, copy in shown]

    numbers = [
        InlineKeyboardButton(
            f"#{index + 1}", callback_data=actions.encode(actions.GET, batch.id, item.id, copy_number(index, copy))
        )
        for index, copy in shown
    ]
    nav = []
    if page > 0:
        nav.append(_page_button(t("btn_prev"), batch, item, page - 1))
    if page < pages - 1:
        nav.append(_page_button(t("btn_next"), batch, item, page + 1))
    rows = [numbers, nav, last_row]
    return "\n".join(lines), InlineKeyboardMarkup([row for row in rows if row])


def _page_button(label: str, batch: Batch, item: Item, page: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=actions.encode(actions.PICKER, batch.id, item.id, page))


def _copy_line(t: Translate, index: int, copy: SearchResult, *, failed: bool) -> str:
    if copy.has_free_slot:
        slot = "🟢"
    else:
        slot = f"🔴 {t('picker_queue', n=copy.queue_length)}" if copy.queue_length else "🔴"
    # Without bit depth or bitrate the quality text is the format itself: do not say it twice.
    known = copy.quality_display != copy.extension.upper()
    fmt = f"  [{copy.extension.upper()}]" if copy.extension and known else ""
    line = (
        f"*#{index + 1}*  {slot}  `{copy.duration_display}`  ·  {copy.quality_display}{fmt}  ·  {copy.size_mb:.0f} MB"
        f"\n    {code_span(copy.basename)}"
    )
    if copy.parent_dir:
        line += f"\n    {code_span(copy.parent_dir)}"
    return f"{line}\n    {t('picker_failed_before')}" if failed else line

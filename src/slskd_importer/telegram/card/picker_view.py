"""The Soulseek copies found for one track, for choosing one by hand."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue.batch import Batch, Item, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import Card
from slskd_importer.telegram.card.status import Translate
from slskd_importer.telegram.ui.markdown import bold, code_span


def render_picker(
    t: Translate, batch: Batch, item: Item, copies: Copies | None, page: int, page_size: int, *, back: str = ""
) -> Card:
    """*copies* None means the search is still running. *back*: callback data of Back (the item view by default)."""
    back = [InlineKeyboardButton(t("btn_back"), callback_data=back or actions.encode(actions.ITEM, batch.id, item.id))]
    if item.status in (ItemStatus.choose, ItemStatus.review):
        back.append(InlineKeyboardButton(t("btn_skip"), callback_data=actions.encode(actions.SKIP, batch.id, item.id)))
    head = bold(item.label)
    if copies is None:
        return f"{head}\n{t('picker_searching')}", InlineKeyboardMarkup([back])
    if not copies.ranked:
        return f"{head}\n{t('item_no_match')}", InlineKeyboardMarkup([back])

    ranked = copies.ranked
    pages = max(1, -(-len(ranked) // page_size))
    page = max(0, min(page, pages - 1))
    start = page * page_size
    shown = list(enumerate(ranked[start : start + page_size], start=start))

    lines = [head, t("picker_lossy" if copies.lossy else "picker_choose", total=len(ranked)), ""]
    lines += [_copy_line(index, copy) for index, copy in shown]

    numbers = [
        InlineKeyboardButton(f"#{index + 1}", callback_data=actions.encode(actions.GET, batch.id, item.id, index))
        for index, _ in shown
    ]
    nav = []
    if page > 0:
        nav.append(_page_button(t("btn_prev"), batch, item, page - 1))
    if page < pages - 1:
        nav.append(_page_button(t("btn_next"), batch, item, page + 1))
    rows = [numbers, nav, back]
    return "\n".join(lines), InlineKeyboardMarkup([row for row in rows if row])


def _page_button(label: str, batch: Batch, item: Item, page: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=actions.encode(actions.PICKER, batch.id, item.id, page))


def _copy_line(index: int, copy: SearchResult) -> str:
    slot = "🟢" if copy.has_free_slot else "🔴"
    fmt = f"  [{copy.extension.upper()}]" if copy.extension else ""
    line = (
        f"*#{index + 1}*  {slot}  `{copy.duration_display}`  ·  {copy.quality_display}{fmt}  ·  {copy.size_mb:.0f} MB"
        f"\n    {code_span(copy.basename)}"
    )
    return f"{line}\n    {code_span(copy.parent_dir)}" if copy.parent_dir else line

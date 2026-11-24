"""Every track of a batch, a page at a time; tap one to open it."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue.batch import RETRYABLE_STATUSES, Batch, Item
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import Card
from slskd_importer.telegram.card.status import ATTENTION, Translate, item_icon, open_action
from slskd_importer.telegram.ui.formatting import clip
from slskd_importer.telegram.ui.markdown import bold

PAGE_SIZE = 8


def attention_first(items: list[Item]) -> list[Item]:
    """Tracks that need a decision first, then the ones that were not downloaded, then the rest in playlist order."""

    def rank(item: Item) -> int:
        if item.status in ATTENTION:
            return 0
        return 1 if item.status in RETRYABLE_STATUSES else 2

    return sorted(items, key=lambda item: (rank(item), item.position))


def render_list(t: Translate, batch: Batch, items: list[Item], progress: dict[int, Progress], page: int) -> Card:
    ordered = attention_first(items)
    pages = max(1, -(-len(ordered) // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    shown = ordered[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    text = f"{bold(batch.name)}\n{t('list_page', page=page + 1, pages=pages, total=len(items))}"
    rows = [
        [
            InlineKeyboardButton(
                clip(f"{item_icon(item, progress.get(item.id))}  {item.label}"),
                callback_data=actions.encode(open_action(item), batch.id, item.id),
            )
        ]
        for item in shown
    ]
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(t("btn_prev"), callback_data=actions.encode(actions.LIST, batch.id, 0, page - 1))
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(t("btn_next"), callback_data=actions.encode(actions.LIST, batch.id, 0, page + 1))
        )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=actions.encode(actions.SUMMARY, batch.id))])
    return text, InlineKeyboardMarkup(rows)

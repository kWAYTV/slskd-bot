"""A batch at a glance: progress, counts, what is in flight, and the tracks that need attention."""

from __future__ import annotations

from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue.batch import OPEN_STATUSES, RETRYABLE_STATUSES, Batch, BatchStatus, Item, ItemStatus
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import Card
from slskd_importer.telegram.card.status import ATTENTION, Translate, item_icon, phase_text
from slskd_importer.telegram.ui.formatting import clip, progress_bar
from slskd_importer.telegram.ui.markdown import bold, escape_md

ATTENTION_BUTTONS = 5


def render_summary(t: Translate, batch: Batch, items: list[Item], progress: dict[int, Progress]) -> Card:
    counts = Counter(item.status for item in items)
    total = len(items)
    settled = total - sum(counts[status] for status in OPEN_STATUSES)

    # A typed list is named "12 tracks" already; only real sources get their kind spelled out.
    lines = [bold(batch.name) if batch.kind == "list" else f"{bold(batch.name)}  ·  {t(f'kind_{batch.kind}')}"]
    if batch.status == BatchStatus.active:
        lines.append(f"{progress_bar(settled / total * 100 if total else 100)}  {settled} / {total}")
    else:
        lines.append(t(f"summary_{batch.status}", total=total))
    tally = _tally(t, batch, counts)
    if tally:
        lines.append(tally)

    working = [item for item in items if item.status == ItemStatus.working]
    if working:
        lines.append("")
        lines += [_working_line(t, item, progress.get(item.id)) for item in working]

    attention = [item for item in items if item.status in ATTENTION]
    return "\n".join(lines), _keyboard(t, batch, counts, attention)


def _tally(t: Translate, batch: Batch, counts: Counter) -> str:
    done_key = "count_saved" if batch.to_library else "count_sent"
    failed = sum(counts[status] for status in RETRYABLE_STATUSES)
    parts = [
        (done_key, counts[ItemStatus.done]),
        ("count_owned", counts[ItemStatus.owned]),
        ("count_review", counts[ItemStatus.review]),
        ("count_failed", failed),
        ("count_removed", counts[ItemStatus.removed]),
        ("count_cancelled", counts[ItemStatus.cancelled]),
    ]
    return "  ·  ".join(t(key, n=n) for key, n in parts if n)


def _working_line(t: Translate, item: Item, progress: Progress | None) -> str:
    return f"{item_icon(item, progress)}  {escape_md(item.label)}  ·  {phase_text(t, progress)}"


def _keyboard(t: Translate, batch: Batch, counts: Counter, attention: list[Item]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                clip(f"{item_icon(item)}  {item.label}"), callback_data=actions.encode(actions.ITEM, batch.id, item.id)
            )
        ]
        for item in attention[:ATTENTION_BUTTONS]
    ]
    last = [InlineKeyboardButton(t("btn_tracks"), callback_data=actions.encode(actions.LIST, batch.id))]
    failed = sum(counts[status] for status in RETRYABLE_STATUSES)
    if failed:
        last.append(
            InlineKeyboardButton(
                t("btn_retry_failed", n=failed), callback_data=actions.encode(actions.RETRY_FAILED, batch.id)
            )
        )
    if batch.status == BatchStatus.active:
        last.append(InlineKeyboardButton(t("btn_cancel"), callback_data=actions.encode(actions.CANCEL, batch.id)))
    rows.append(last)
    return InlineKeyboardMarkup(rows)

"""A batch at a glance: where it stands, the counts, what is in flight, and the tracks waiting for a decision."""

from __future__ import annotations

from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue.batch import (
    OPEN_STATUSES,
    RETRYABLE_STATUSES,
    WAITING_STATUSES,
    Batch,
    BatchStatus,
    Item,
    ItemStatus,
)
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import Card
from slskd_importer.telegram.card.status import ATTENTION, Translate, item_icon, open_action, phase_text
from slskd_importer.telegram.ui.formatting import clip, progress_bar
from slskd_importer.telegram.ui.markdown import bold, escape_md

# Kept small: a card is one Telegram message (4096 characters) and one screen of buttons.
ATTENTION_BUTTONS = 6
WORKING_LINES = 5


def batch_title(t: Translate, batch: Batch, total: int) -> str:
    """The batch's name as shown on cards: a typed list is named by its size, in the chat's language."""
    if batch.kind == "list":
        return bold(t("list_name", n=total))
    return f"{bold(batch.name)}  ·  {t(f'kind_{batch.kind}')}"


def render_summary(t: Translate, batch: Batch, items: list[Item], progress: dict[int, Progress]) -> Card:
    counts = Counter(item.status for item in items)
    total = len(items)
    in_flight = sum(counts[status] for status in OPEN_STATUSES)

    lines = [batch_title(t, batch, total), _headline(t, batch, counts, total, in_flight)]
    tally = _tally(t, batch, counts)
    if tally:
        lines.append(tally)
    lines += _working_lines(t, items, progress)

    attention = sorted(
        (item for item in items if item.status in ATTENTION),
        # Saved-but-doubted and lossy-only tracks first: the ones waiting for a pick have their own button.
        key=lambda item: (item.status == ItemStatus.choose, item.position),
    )
    return "\n".join(lines), _keyboard(t, batch, counts, attention, in_flight)


def _headline(t: Translate, batch: Batch, counts: Counter, total: int, in_flight: int) -> str:
    """Where the batch stands: working, waiting for the requester, or finished."""
    if in_flight:
        settled = total - in_flight
        return f"{progress_bar(settled / total * 100 if total else 100)}  {settled} / {total}"
    if batch.status == BatchStatus.cancelled:
        return t("summary_cancelled", total=total)
    if counts[ItemStatus.choose]:
        return t("summary_waiting", n=counts[ItemStatus.choose])
    to_review = counts[ItemStatus.review] + counts[ItemStatus.doubt]
    if to_review:
        return t("summary_review", n=to_review)
    return t("summary_done", total=total)


def _tally(t: Translate, batch: Batch, counts: Counter) -> str:
    done_key = "count_saved" if batch.to_library else "count_sent"
    parts = [
        (done_key, counts[ItemStatus.done]),
        ("count_choose", counts[ItemStatus.choose]),
        ("count_review", counts[ItemStatus.review] + counts[ItemStatus.doubt]),
        ("count_owned", counts[ItemStatus.owned]),
        ("count_failed", sum(counts[status] for status in RETRYABLE_STATUSES)),
        ("count_removed", counts[ItemStatus.removed]),
        ("count_cancelled", counts[ItemStatus.cancelled]),
    ]
    return "  ·  ".join(t(key, n=n) for key, n in parts if n)


def _working_lines(t: Translate, items: list[Item], progress: dict[int, Progress]) -> list[str]:
    """A few tracks in flight by name; the rest, and the ones waiting in peer queues, as counts."""
    working = [item for item in items if item.status == ItemStatus.working]
    if not working:
        return []
    parked = [item for item in working if (state := progress.get(item.id)) is not None and state.queued]
    busy = [item for item in working if item not in parked]
    lines = [""]
    lines += [
        f"{item_icon(item, progress.get(item.id))}  {escape_md(item.label)}  ·  {phase_text(t, progress.get(item.id))}"
        for item in busy[:WORKING_LINES]
    ]
    if len(busy) > WORKING_LINES:
        lines.append(t("summary_more", n=len(busy) - WORKING_LINES))
    if parked:
        lines.append(t("summary_parked", n=len(parked)))
    return lines


def _keyboard(
    t: Translate, batch: Batch, counts: Counter, attention: list[Item], in_flight: int
) -> InlineKeyboardMarkup:
    def batch_button(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(label, callback_data=actions.encode(action, batch.id))

    rows = []
    to_pick = counts[ItemStatus.choose]
    if to_pick:
        rows.append([batch_button(t("btn_tour", n=to_pick), actions.TOUR)])
    rows += [
        [
            InlineKeyboardButton(
                clip(f"{item_icon(item)}  {item.label}"),
                callback_data=actions.encode(open_action(item), batch.id, item.id),
            )
        ]
        for item in attention[:ATTENTION_BUTTONS]
    ]
    last = [batch_button(t("btn_tracks"), actions.LIST)]
    failed = sum(counts[status] for status in RETRYABLE_STATUSES)
    if failed:
        last.append(batch_button(t("btn_retry_failed", n=failed), actions.RETRY_FAILED))
    if in_flight:
        last.append(batch_button(t("btn_cancel"), actions.CANCEL))
    rows.append(last)
    waiting = sum(counts[status] for status in WAITING_STATUSES)
    if waiting > 1:
        rows.append([batch_button(t("btn_skip_all", n=waiting), actions.SKIP_ALL)])
    return InlineKeyboardMarkup(rows)

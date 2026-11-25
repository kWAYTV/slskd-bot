"""One track on a card: what happened to it and what can be done next."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.queue import progress as phases
from slskd_importer.queue.batch import SAVED_STATUSES, Batch, Item, ItemStatus
from slskd_importer.queue.pipeline import VERDICT_PREFIX
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.status import Translate, identity_lines, item_icon
from slskd_importer.telegram.ui.formatting import progress_bar
from slskd_importer.telegram.ui.markdown import bold, code_span, escape_md

Card = tuple[str, InlineKeyboardMarkup | None]


def render_item(
    t: Translate, batch: Batch, item: Item, progress: Progress | None, *, alone: bool, back: str = ""
) -> Card:
    """*alone*: the batch is this one track, so the card offers Cancel instead of Back.

    *back*: callback data of the Back button (where the track was opened from); the track list by default.
    """
    track = item.track
    head = f"{item_icon(item, progress)}  {bold(item.label)}"
    if track is not None and track.duration_ms:
        head += f"  ·  {track.duration_display}"
    lines = [head, *_body(t, batch, item, progress)]
    return "\n".join(lines), _keyboard(t, batch, item, alone=alone, back=back)


def _body(t: Translate, batch: Batch, item: Item, progress: Progress | None) -> list[str]:
    status = item.status
    if status == ItemStatus.pending:
        return [t("item_pending")]
    if status == ItemStatus.working:
        return _working(t, progress)
    if status in SAVED_STATUSES:
        first = t("item_saved", name=code_span(item.saved_name)) if batch.to_library else t("item_sent")
        lines = [first, *(line for line in (escape_md(item.quality), _detail(t, item.detail)) if line)]
        return [*lines, t("item_doubt")] if status == ItemStatus.doubt else lines
    if status == ItemStatus.owned:
        return [t("item_owned"), code_span(item.saved_name)]
    lines = [t(f"item_{status}")]
    if item.detail and status in (ItemStatus.review, ItemStatus.failed):
        lines.append(escape_md(item.detail))
    if status in (ItemStatus.no_match, ItemStatus.failed, ItemStatus.choose, ItemStatus.review):
        # Nothing (right) was found: the first thing to check is whether the song was understood.
        lines += identity_lines(t, item)
    return lines


def _detail(t: Translate, detail: str) -> str:
    """A stored lossless verdict (``verdict:WARNING:19.5``) in the chat's language; other details as they are."""
    if not detail.startswith(VERDICT_PREFIX):
        return escape_md(detail)
    _, _, rest = detail.partition(":")
    kind, _, khz = rest.partition(":")
    return t(f"verdict_{kind.lower()}", khz=khz)


def _working(t: Translate, progress: Progress | None) -> list[str]:
    if progress is None:
        return [t("item_pending")]
    if progress.phase != phases.DOWNLOADING:
        return [t(f"item_{progress.phase}")]
    if progress.queued:
        return [t("item_queued_peer")]
    percent = progress.percent or 0.0
    return [f"{t('item_downloading')}  {percent:.0f}%", progress_bar(percent)]


def _keyboard(t: Translate, batch: Batch, item: Item, *, alone: bool, back: str) -> InlineKeyboardMarkup | None:
    def button(label_key: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(t(label_key), callback_data=actions.encode(action, batch.id, item.id))

    status = item.status
    row: list[InlineKeyboardButton] = []
    if status == ItemStatus.doubt:
        row += [
            button("btn_keep", actions.KEEP),
            button("btn_other_versions", actions.PICKER),
            button("btn_undo", actions.UNDO),
        ]
    elif status == ItemStatus.done:
        row.append(button("btn_other_versions", actions.PICKER))
        if batch.to_library:
            row += [button("btn_undo", actions.UNDO), button("btn_send_file", actions.SEND)]
    elif status == ItemStatus.owned:
        row.append(button("btn_anyway", actions.AGAIN))
    elif status in (ItemStatus.review, ItemStatus.choose):
        row += [button("btn_choose", actions.PICKER), button("btn_skip", actions.SKIP)]
    elif status == ItemStatus.no_match:
        row += [button("btn_search_again", actions.RETRY), button("btn_skip", actions.SKIP)]
    elif status == ItemStatus.failed:
        row += [
            button("btn_retry", actions.RETRY),
            button("btn_choose", actions.PICKER),
            button("btn_skip", actions.SKIP),
        ]
    elif status in (ItemStatus.removed, ItemStatus.cancelled):
        row.append(button("btn_again", actions.AGAIN))
    elif alone:
        row.append(button("btn_cancel", actions.CANCEL))

    rows = [row] if row else []
    if not alone:
        rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back or actions.encode(actions.LIST, batch.id))])
    return InlineKeyboardMarkup(rows) if rows else None

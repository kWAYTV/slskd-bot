"""How a queue item's state reads on a card: its icon and its one-line status."""

from __future__ import annotations

from collections.abc import Callable

from slskd_importer.queue import progress as phases
from slskd_importer.queue.batch import Item, ItemStatus
from slskd_importer.queue.progress import Progress
from slskd_importer.telegram.card import actions

# ``t(key, **kwargs)`` bound to the chat's locale.
Translate = Callable[..., str]

_STATUS_ICONS = {
    ItemStatus.pending: "⏳",
    ItemStatus.working: "⬇️",
    ItemStatus.done: "✅",
    ItemStatus.doubt: "⚠️",
    ItemStatus.owned: "📀",
    ItemStatus.review: "👂",
    ItemStatus.choose: "👉",
    ItemStatus.no_match: "🤷",
    ItemStatus.failed: "❌",
    ItemStatus.removed: "↩️",
    ItemStatus.cancelled: "⏹",
}
_PHASE_ICONS = {
    phases.IDENTIFYING: "🔎",
    phases.SEARCHING: "🔎",
    phases.DOWNLOADING: "⬇️",
    phases.CHECKING: "🔬",
    phases.SAVING: "💾",
    phases.SENDING: "📤",
}

# Items waiting for a decision from the requester, in the order a summary lists them. Tracks that
# were not found or failed are not among them: there is nothing to decide, they are counted and can be
# retried together.
ATTENTION = (ItemStatus.choose, ItemStatus.doubt, ItemStatus.review)


def open_action(item: Item) -> str:
    """What tapping a track does: a track waiting for a pick opens on its copies, any other on itself."""
    return actions.PICKER if item.status == ItemStatus.choose else actions.ITEM


def item_icon(item: Item, progress: Progress | None = None) -> str:
    if item.status == ItemStatus.working and progress is not None:
        return _PHASE_ICONS.get(progress.phase, "⬇️")
    return _STATUS_ICONS.get(item.status, "•")


def phase_text(t: Translate, progress: Progress | None) -> str:
    """Short words for what a working item is doing: ``42%``, ``searching``, ``queued at peer``."""
    if progress is None:
        return t("phase_starting")
    if progress.phase == phases.DOWNLOADING:
        if progress.queued:
            return t("phase_queued")
        return f"{progress.percent or 0:.0f}%"
    return t(f"phase_{progress.phase}")

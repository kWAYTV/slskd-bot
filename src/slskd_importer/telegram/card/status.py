"""How a queue item's state reads on a card: its icon and its one-line status."""

from __future__ import annotations

from collections.abc import Callable

from slskd_importer.queue import progress as phases
from slskd_importer.queue.batch import Item, ItemStatus
from slskd_importer.queue.progress import Progress

# ``t(key, **kwargs)`` bound to the chat's locale.
Translate = Callable[..., str]

_STATUS_ICONS = {
    ItemStatus.pending: "⏳",
    ItemStatus.working: "⬇️",
    ItemStatus.done: "✅",
    ItemStatus.owned: "📀",
    ItemStatus.review: "👂",
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

# Items the requester may want to act on, in the order a summary lists them.
ATTENTION = (ItemStatus.review, ItemStatus.failed, ItemStatus.no_match)


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

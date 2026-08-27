"""Per-chat conversation state and cancellation.

Searches are keyed by ``search_id`` (not chat_id) so two queries in the same
chat stay independent. ``/cancel`` still stops everything in that chat.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult


def split_search_callback(data: str) -> tuple[str, str] | None:
    """Parse ``prefix:search_id`` or ``prefix:search_id:rest``.

    Returns ``(search_id, rest)`` where *rest* is ``""`` when absent.
    """
    parts = data.split(":", 2)
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        return parts[1], ""
    return parts[1], parts[2]


@dataclass
class PendingSearch:
    """Holds state for one search session (one Telegram result/picker message)."""

    query: str
    track: TrackInfo | None = None
    results: list[SearchResult] = field(default_factory=list)
    message_id: int | None = None
    is_fallback: bool = False
    page: int = 0
    user_id: int | None = None
    search_id: str = ""
    chat_id: int = 0
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    picked_index: int | None = None
    pick_state: str = ""


@dataclass
class PendingDownload:
    """Tracks a single file download waiting for approval."""

    track: TrackInfo
    result: SearchResult
    chat_id: int
    source_path: str | None = None
    status_message_id: int | None = None
    approval_message_id: int | None = None
    result_index: int = 0
    user_id: int | None = None
    transfer_id: str | None = None
    progress_percent: float | None = None
    transfer_state: str | None = None
    created_at: float = field(default_factory=time.time)
    search_id: str | None = None
    task: asyncio.Task | None = None
    origin_message_id: int | None = None


class ChatSession:
    """In-memory per-chat state for searches, downloads, and cancellation."""

    def __init__(self) -> None:
        self.pending: dict[str, PendingSearch] = {}
        self.downloads: dict[str, PendingDownload] = {}
        self._dl_counter = 0
        self._search_counter = 0
        self._spotify_candidates: dict[str, list[TrackInfo]] = {}
        self._spotify_page: dict[str, int] = {}
        self._chat_generation: dict[int, int] = {}
        self._active_tasks: dict[int, set[asyncio.Task]] = {}
        self._active_import: dict[int, int] = {}
        self._import_pending: dict[int, PendingSearch] = {}
        self._import_status_msg: dict[int, object] = {}
        self._quality_overrides: dict[int, str] = {}
        self._locales: dict[int, str] = {}

    def next_dl_id(self) -> str:
        self._dl_counter += 1
        return str(self._dl_counter)

    def next_search_id(self) -> str:
        self._search_counter += 1
        return str(self._search_counter)

    def searches_for_chat(self, chat_id: int) -> list[PendingSearch]:
        return [search for search in self.pending.values() if search.chat_id == chat_id]

    def search_cancelled(self, search_id: str | None) -> bool:
        if not search_id:
            return False
        search = self.pending.get(search_id)
        return search is None or search.cancelled

    def drop_search(self, search_id: str) -> PendingSearch | None:
        search = self.pending.pop(search_id, None)
        self._spotify_candidates.pop(search_id, None)
        self._spotify_page.pop(search_id, None)
        return search

    def cancel_chat_operations(self, chat_id: int) -> tuple[bool, list[PendingDownload], list[PendingSearch]]:
        """Cancel all active operations for a chat.

        Bumps the generation counter and cancels tracked background tasks.
        Returns (had_work, downloads that need slskd/disk cleanup, searches to notify).
        """
        stale_searches = self.searches_for_chat(chat_id)
        had_work = bool(stale_searches or self._active_tasks.get(chat_id) or self._import_pending.get(chat_id))

        self._chat_generation[chat_id] = self._chat_generation.get(chat_id, 0) + 1

        for task in self._active_tasks.pop(chat_id, set()):
            task.cancel()

        for search in stale_searches:
            search.cancelled = True
            self.drop_search(search.search_id)

        self._import_pending.pop(chat_id, None)
        self._import_status_msg.pop(chat_id, None)

        stale = [v for v in self.downloads.values() if v.chat_id == chat_id]
        if stale:
            had_work = True
        stale_ids = [k for k, v in self.downloads.items() if v.chat_id == chat_id]
        for dl_id in stale_ids:
            del self.downloads[dl_id]

        return had_work, stale, stale_searches

    def is_stale(self, chat_id: int, generation: int) -> bool:
        return self._chat_generation.get(chat_id, 0) != generation

    def track_task(self, chat_id: int, task: asyncio.Task):
        self._active_tasks.setdefault(chat_id, set()).add(task)

        def _on_done(t: asyncio.Task) -> None:
            tasks = self._active_tasks.get(chat_id)
            if tasks is not None:
                tasks.discard(t)
                if not tasks:
                    del self._active_tasks[chat_id]

        task.add_done_callback(_on_done)

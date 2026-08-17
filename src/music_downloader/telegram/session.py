"""Per-chat conversation state and cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult


@dataclass
class PendingSearch:
    """Holds state for an active search session."""

    query: str
    track: TrackInfo | None = None
    results: list[SearchResult] = field(default_factory=list)
    message_id: int | None = None
    is_fallback: bool = False
    page: int = 0


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


class ChatSession:
    """In-memory per-chat state for searches, downloads, and cancellation."""

    def __init__(self) -> None:
        self.pending: dict[int, PendingSearch] = {}
        self.downloads: dict[str, PendingDownload] = {}
        self._dl_counter = 0
        self._spotify_candidates: dict[int, list[TrackInfo]] = {}
        self._spotify_page: dict[int, int] = {}
        self._awaiting_direct_metadata: dict[int, str] = {}
        self._chat_generation: dict[int, int] = {}
        self._active_tasks: dict[int, set[asyncio.Task]] = {}
        self._active_import: dict[int, int] = {}
        self._import_pending: dict[int, PendingSearch] = {}

    def next_dl_id(self) -> str:
        self._dl_counter += 1
        return str(self._dl_counter)

    def cancel_chat_operations(self, chat_id: int) -> bool:
        """Cancel all active operations for a chat.

        Bumps the generation counter and cancels tracked background tasks.
        Returns True if something was actually cancelled.
        """
        had_work = bool(
            self.pending.get(chat_id) or self._spotify_candidates.get(chat_id) or self._active_tasks.get(chat_id)
        )

        self._chat_generation[chat_id] = self._chat_generation.get(chat_id, 0) + 1

        for task in self._active_tasks.pop(chat_id, set()):
            task.cancel()

        self.pending.pop(chat_id, None)
        self._import_pending.pop(chat_id, None)
        self._spotify_candidates.pop(chat_id, None)
        self._spotify_page.pop(chat_id, None)
        self._awaiting_direct_metadata.pop(chat_id, None)

        stale_ids = [k for k, v in self.downloads.items() if v.chat_id == chat_id]
        for dl_id in stale_ids:
            del self.downloads[dl_id]

        return had_work

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

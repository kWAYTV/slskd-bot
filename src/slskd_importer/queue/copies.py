"""The Soulseek copies found for queue items, remembered so a manual pick needs no second search.

They are kept in the database, not only in memory: a track is often reviewed
long after its search, and across restarts.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.confidence import sure_copies
from slskd_importer.queue.pick import decode_copies, encode_copies
from slskd_importer.queue.store import QueueRepository
from slskd_importer.settings.config import Config
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.fallbacks import search_with_fallbacks
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.soulseek.scoring import ResultScorer

# Items whose copies stay in memory; the rest are read back from the store when asked for.
CACHED_ITEMS = 300
REMEMBERED_COPIES = 20


@dataclass
class Copies:
    """Ranked copies of one track. *lossy* is True when no lossless copy was found."""

    ranked: list[SearchResult] = field(default_factory=list)
    lossy: bool = False


class CopyFinder:
    def __init__(
        self, config: Config, slskd: SlskdClient, scorer: ResultScorer, store: QueueRepository | None = None
    ) -> None:
        self._config = config
        self._slskd = slskd
        self._scorer = scorer
        self._store = store
        self._found: OrderedDict[int, Copies] = OrderedDict()

    def remembered(self, item_id: int) -> Copies | None:
        """The copies found for an item earlier, or None when it was never searched."""
        copies = self._found.get(item_id)
        if copies is None and self._store is not None:
            stored = self._store.load_copies(item_id)
            if stored is not None:
                copies = Copies(decode_copies(stored[1]), stored[0])
                self._cache(item_id, copies)
        return copies

    def forget(self, item_id: int) -> None:
        """Drop the cached copies of an item (it was renamed; the store's row goes with the rename)."""
        self._found.pop(item_id, None)

    async def find(self, item_id: int, track: TrackInfo) -> Copies:
        """Search Soulseek with the four-tier fallbacks and remember the best copies for *item_id*.

        Only copies whose path names the song are kept: the looser fallback
        queries also return other artists' songs with the same title, and those
        are not worth showing, let alone fetching.
        """
        ranked, lossy, _cancelled = await search_with_fallbacks(
            self._slskd,
            self._scorer,
            track,
            timeout_secs=self._config.search_timeout_secs,
            is_cancelled=lambda: False,
        )
        copies = Copies(sure_copies(track, ranked)[:REMEMBERED_COPIES], lossy)
        self._cache(item_id, copies)
        if self._store is not None:
            await asyncio.to_thread(self._store.save_copies, item_id, lossy, encode_copies(copies.ranked))
        return copies

    def _cache(self, item_id: int, copies: Copies) -> None:
        self._found[item_id] = copies
        self._found.move_to_end(item_id)
        while len(self._found) > CACHED_ITEMS:
            self._found.popitem(last=False)

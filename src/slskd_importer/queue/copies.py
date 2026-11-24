"""The Soulseek copies found for queue items, remembered so a manual pick needs no second search."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.settings.config import Config
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.fallbacks import search_with_fallbacks
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.soulseek.scoring import ResultScorer

REMEMBERED_ITEMS = 300
REMEMBERED_COPIES = 20


@dataclass
class Copies:
    """Ranked copies of one track. *lossy* is True when no lossless copy was found."""

    ranked: list[SearchResult] = field(default_factory=list)
    lossy: bool = False


class CopyFinder:
    def __init__(self, config: Config, slskd: SlskdClient, scorer: ResultScorer) -> None:
        self._config = config
        self._slskd = slskd
        self._scorer = scorer
        self._found: OrderedDict[int, Copies] = OrderedDict()

    def remembered(self, item_id: int) -> Copies | None:
        return self._found.get(item_id)

    async def find(self, item_id: int, track: TrackInfo) -> Copies:
        """Search Soulseek with the four-tier fallbacks and remember the best copies for *item_id*."""
        ranked, lossy, _cancelled = await search_with_fallbacks(
            self._slskd,
            self._scorer,
            track,
            timeout_secs=self._config.search_timeout_secs,
            is_cancelled=lambda: False,
        )
        copies = Copies(ranked[:REMEMBERED_COPIES], lossy)
        self._found[item_id] = copies
        self._found.move_to_end(item_id)
        while len(self._found) > REMEMBERED_ITEMS:
            self._found.popitem(last=False)
        return copies

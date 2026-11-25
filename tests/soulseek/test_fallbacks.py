"""The tiered Soulseek search: which queries are tried, and in which order."""

from unittest.mock import AsyncMock, MagicMock

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.fallbacks import search_with_fallbacks
from slskd_importer.soulseek.scoring import ResultScorer


def response(name: str) -> dict:
    return {"username": "peer", "hasFreeUploadSlot": True, "files": [{"filename": f"\\music\\{name}", "size": 1}]}


async def run(track: TrackInfo, answers: dict[str, list]):
    client = MagicMock()
    client.search = AsyncMock(side_effect=lambda query, **kwargs: answers.get(query, []))
    ranked, _lossy, _cancelled = await search_with_fallbacks(
        client, ResultScorer(), track, timeout_secs=5, is_cancelled=lambda: False
    )
    return ranked, [call.args[0] for call in client.search.await_args_list]


async def test_punctuation_is_dropped_when_the_name_as_written_finds_nothing():
    track = TrackInfo("A.Morgan", "Decision", "", 0, "", "")
    ranked, queries = await run(track, {"A Morgan Decision": [response("A. Morgan - Decision.flac")]})
    assert queries == ["A.Morgan Decision", "A Morgan Decision"]
    assert [copy.basename for copy in ranked] == ["A. Morgan - Decision.flac"]


async def test_a_plain_name_is_not_searched_twice():
    track = TrackInfo("Kuss", "Obsessed", "", 0, "", "")
    _ranked, queries = await run(track, {})
    assert queries[:2] == ["Kuss Obsessed", "Obsessed"]

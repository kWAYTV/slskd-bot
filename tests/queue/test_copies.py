"""The copy finder keeps only copies that name the song, and remembers them per item."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from slskd_importer.queue.copies import CACHED_ITEMS as REMEMBERED_ITEMS
from slskd_importer.queue.copies import CopyFinder
from slskd_importer.soulseek.result import SearchResult
from tests.queue.helpers import make_result, make_track

SEARCH = "slskd_importer.queue.copies.search_with_fallbacks"
LOOK_ALIKE = SearchResult(username="u", filename="\\Music\\Cher - Bang Bang.flac", size=1, length=162)


def finder() -> CopyFinder:
    return CopyFinder(SimpleNamespace(search_timeout_secs=5), MagicMock(), MagicMock())


async def test_look_alikes_are_dropped():
    copies = finder()
    with patch(SEARCH, AsyncMock(return_value=([LOOK_ALIKE, make_result(4)], False, False))):
        found = await copies.find(1, make_track())
    assert [copy.username for copy in found.ranked] == ["user4"]
    assert copies.remembered(1) is found


async def test_only_look_alikes_means_nothing_found():
    with patch(SEARCH, AsyncMock(return_value=([LOOK_ALIKE], False, False))):
        found = await finder().find(1, make_track())
    assert found.ranked == []


async def test_lossy_flag_is_kept_and_old_items_are_forgotten():
    copies = finder()
    with patch(SEARCH, AsyncMock(return_value=([make_result(0, "mp3")], True, False))):
        for item_id in range(REMEMBERED_ITEMS + 2):
            found = await copies.find(item_id, make_track())
    assert found.lossy is True
    assert copies.remembered(0) is None and copies.remembered(REMEMBERED_ITEMS + 1) is not None


async def test_copies_survive_a_restart(tmp_path):
    from tests.queue.helpers import make_batch, make_store

    store = make_store(tmp_path)
    item = store.items(make_batch(store).id)[0]
    first = CopyFinder(SimpleNamespace(search_timeout_secs=5), MagicMock(), MagicMock(), store)
    with patch(SEARCH, AsyncMock(return_value=([make_result(0), make_result(1, "mp3")], True, False))):
        await first.find(item.id, make_track())

    after_restart = CopyFinder(SimpleNamespace(search_timeout_secs=5), MagicMock(), MagicMock(), store)
    remembered = after_restart.remembered(item.id)
    assert remembered.lossy is True
    assert remembered.ranked == [make_result(0), make_result(1, "mp3")]
    assert after_restart.remembered(item.id + 99) is None

"""LibrarySweep.abort marks the run interrupted."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from slskd_importer.records.database import Database
from slskd_importer.records.sweep_models import RUN_INTERRUPTED
from slskd_importer.sweep.runner import LibrarySweep


@pytest.mark.asyncio
async def test_abort_marks_interrupted(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    config = MagicMock()
    config.library_sweep_users = set()
    config.telegram_library_users = {1}
    config.telegram_allowed_users = {1}
    config.output_dir = str(tmp_path / "music")
    config.library_sweep_schedule = "off"
    config.library_sweep_pause_secs = 0
    config.library_sweep_keep_days = 7
    config.search_timeout_secs = 1
    config.download_timeout_secs = 1
    (tmp_path / "music").mkdir()

    sweep = LibrarySweep(
        config,
        db,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    async def _hang(_run):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    sweep._sweep = _hang  # type: ignore[method-assign]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("slskd_importer.sweep.runner.rules.missing_tools", lambda: [])
        run, why = sweep.start("telegram")
    assert why == "" and run is not None
    assert sweep.running
    aborted = await sweep.abort()
    assert aborted is not None
    assert aborted.status == RUN_INTERRUPTED
    assert not sweep.running
    saved = sweep.repo.latest_run()
    assert saved is not None
    assert saved.status == RUN_INTERRUPTED

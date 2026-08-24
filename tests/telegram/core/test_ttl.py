from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.telegram.core import ttl
from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingDownload
from tests.telegram.helpers import _make_config, _make_search_result, _make_track


class TestExpireStaleApprovals:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_expires_old_awaiting_approval(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.config.approval_ttl_secs = 60
        bot._cleanup_download_artifacts = AsyncMock()
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            source_path="/tmp/old.flac",
            approval_message_id=7,
            created_at=time.time() - 120,
        )
        app = AsyncMock()
        app.bot.edit_message_caption = AsyncMock()
        await bot.expire_stale_approvals(app)
        assert "1" not in bot.downloads
        bot._cleanup_download_artifacts.assert_awaited_once()
        app.bot.edit_message_caption.assert_awaited_once()

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_keeps_fresh_and_in_flight(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.config.approval_ttl_secs = 60
        bot._cleanup_download_artifacts = AsyncMock()
        bot.downloads["fresh"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            source_path="/tmp/fresh.flac",
            created_at=time.time(),
        )
        bot.downloads["inflight"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            source_path=None,
            created_at=time.time() - 9999,
        )
        await bot.expire_stale_approvals(AsyncMock())
        assert "fresh" in bot.downloads
        assert "inflight" in bot.downloads
        bot._cleanup_download_artifacts.assert_not_awaited()


class TestApprovalTtlLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop_cancels_task(self):
        app = MagicMock()
        app.bot_data = {}
        ttl.start_approval_ttl(MagicMock(), app)
        task = app.bot_data["approval_ttl_task"]
        assert not task.done()
        await ttl.stop_approval_ttl(app)
        assert task.done()
        assert "approval_ttl_task" not in app.bot_data

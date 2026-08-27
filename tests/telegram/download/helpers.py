"""Shared mock builders for download flow tests."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult


def _make_config():
    td = tempfile.mkdtemp()
    config = MagicMock()
    config.telegram_bot_token = "test-token"
    config.spotify_client_id = "test-id"
    config.spotify_client_secret = "test-secret"
    config.slskd_host = "http://localhost:5030"
    config.slskd_api_key = "test-key"
    config.telegram_allowed_users = set()
    config.max_results = 5
    config.max_concurrent_downloads = 3
    config.approval_ttl_secs = 86400
    config.duration_tolerance_secs = 5
    config.exclude_keywords = ["live", "remix"]
    config.download_dir = os.path.join(td, "downloads")
    config.output_dir = os.path.join(td, "music")
    config.data_dir = os.path.join(td, "data")
    config.filename_template = "{artist} - {title}"
    config.search_timeout_secs = 30
    config.download_timeout_secs = 600
    config.telegram_library_users = set()
    config.telegram_api_base_url = ""
    config.telegram_file_limit = 50 * 1024 * 1024
    return config


def _make_track():
    return TrackInfo(
        artist="Nancy Sinatra",
        title="Bang Bang",
        album="How Does That Grab You?",
        duration_ms=162_000,
        spotify_url="https://open.spotify.com/track/xxx",
        year="1966",
    )


def _make_result(idx=0, ext="flac"):
    return SearchResult(
        username=f"user{idx}",
        filename=f"\\Music\\Nancy Sinatra - Bang Bang {idx}.{ext}",
        size=30_000_000,
        bit_rate=900,
        bit_depth=16,
        sample_rate=44100,
        length=162,
        has_free_slot=True,
        upload_speed=1_000_000,
        queue_length=0,
    )


def _make_context():
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_audio = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.edit_message_reply_markup = AsyncMock()
    context.bot.edit_message_caption = AsyncMock()
    context.bot.edit_message_text = AsyncMock()
    context.bot.delete_message = AsyncMock()
    context.application = MagicMock()
    context.application.create_task = MagicMock(return_value=MagicMock())
    return context

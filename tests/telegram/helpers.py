"""Shared mock builders for Telegram conversation tests."""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult


def _make_config():
    """Create a mock Config object with isolated DB per instance."""
    td = tempfile.mkdtemp()
    config = MagicMock()
    config.telegram_bot_token = "test-token"
    config.spotify_client_id = "test-id"
    config.spotify_client_secret = "test-secret"
    config.slskd_host = "http://localhost:5030"
    config.slskd_api_key = "test-key"
    config.telegram_allowed_users = {12345}
    config.max_results = 5
    config.max_concurrent_downloads = 3
    config.approval_ttl_secs = 86400
    config.quality_preference = "hires"
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


def _make_search_result(idx=0):
    return SearchResult(
        username=f"user{idx}",
        filename=f"\\Music\\Nancy Sinatra - Bang Bang {idx}.flac",
        size=30_000_000,
        bit_rate=900,
        bit_depth=16,
        sample_rate=44100,
        length=162,
        has_free_slot=True,
        upload_speed=1_000_000,
        queue_length=0,
    )


def _make_update(user_id=12345, chat_id=67890, text="Nancy Sinatra Bang Bang"):
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message = AsyncMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_callback_update(user_id=12345, chat_id=67890, data="dl:0"):
    """Create a mock callback query Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.callback_query = AsyncMock()
    update.callback_query.from_user.id = user_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_caption = AsyncMock()
    return update


def _make_context(chat_id=67890):
    """Create a mock context."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_audio = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.edit_message_reply_markup = AsyncMock()
    context.bot.edit_message_caption = AsyncMock()
    context.bot.edit_message_text = AsyncMock()
    context.application = MagicMock()
    context.application.create_task = MagicMock(side_effect=lambda coro, **kw: asyncio.ensure_future(coro))
    return context

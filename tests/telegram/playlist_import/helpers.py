"""Shared mock builders for playlist import flow tests."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.playlist_import import ImportJob, ImportTrack
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.core.app import MusicBot


async def _fake_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _make_config():
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
        artist="Artist",
        title="Title",
        album="Album",
        duration_ms=162000,
        spotify_url="https://open.spotify.com/track/xxx",
        year="2024",
    )


def _make_result(idx=0):
    return SearchResult(
        username=f"user{idx}",
        filename=f"\\Music\\track{idx}.flac",
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
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    context.bot.send_audio = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.delete_message = AsyncMock()
    context.application = MagicMock()
    context.application.create_task = MagicMock(return_value=MagicMock())
    return context


def _make_update(chat_id=67890, user_id=12345, text="/import https://open.spotify.com/playlist/abc123"):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_caption = AsyncMock()
    return update


@patch("slskd_importer.telegram.core.app.SpotifyResolver")
@patch("slskd_importer.telegram.core.app.SlskdClient")
def _setup_bot(mock_slskd_cls, mock_spotify_cls):
    config = _make_config()
    mock_slskd_cls.return_value = MagicMock()
    mock_spotify_cls.return_value = MagicMock()
    bot = MusicBot(config)
    bot.slskd = mock_slskd_cls.return_value
    bot.slskd.search = AsyncMock(return_value=[])
    bot.slskd.enqueue_download = MagicMock(return_value=True)
    bot.slskd.wait_for_download = AsyncMock()
    bot.import_repo = MagicMock()
    bot.import_repo.get_active_job = MagicMock(return_value=None)
    bot.playlist_resolver = MagicMock()
    return bot


def _make_import_job(job_id=1, chat_id=67890, status="active"):
    return ImportJob(
        id=job_id,
        chat_id=chat_id,
        spotify_url="https://open.spotify.com/playlist/abc123",
        name="Test Playlist",
        total_tracks=10,
        completed_tracks=3,
        failed_tracks=1,
        skipped_tracks=0,
        status=status,
        created_at="2024-01-01",
        updated_at="2024-01-01",
    )


def _make_import_track(track_id=1, job_id=1, position=1):
    return ImportTrack(
        id=track_id,
        job_id=job_id,
        position=position,
        artist="Artist",
        title="Title",
        album="Album",
        duration_ms=162000,
        spotify_url="https://open.spotify.com/track/xxx",
        year="2024",
        status="pending",
        error_message="",
        created_at="2024-01-01",
        updated_at="2024-01-01",
    )

"""Authorization gates."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_update,
)


class TestMusicBotAuthorization:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    def test_is_authorized_empty_denies_all(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = set()
        bot = MusicBot(config)
        assert bot._is_authorized(99999) is False

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    def test_is_authorized_allowed(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {12345, 67890}
        bot = MusicBot(config)
        assert bot._is_authorized(12345) is True
        assert bot._is_authorized(99999) is False

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_check_auth_denied(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999)
        result = await bot._check_auth(update)
        assert result is False
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_check_auth_allowed(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {12345}
        bot = MusicBot(config)
        update = _make_update()
        result = await bot._check_auth(update)
        assert result is True

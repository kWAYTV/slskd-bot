"""PTB application wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from music_downloader.telegram.core.app import create_bot
from tests.telegram.download.helpers import _make_config


class TestCreateBot:
    def test_creates_application(self):
        config = _make_config()
        with patch("music_downloader.telegram.core.app.Application") as mock_app_cls:
            mock_builder = MagicMock()
            mock_app = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.post_init.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            app = create_bot(config)
            assert app is mock_app
            mock_app.add_handler.assert_called()
            # locale middleware + 10 command handlers + callback + text message
            assert mock_app.add_handler.call_count == 13

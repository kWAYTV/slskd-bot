"""PTB application wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from slskd_importer.telegram.core.app import create_bot
from tests.telegram.download.helpers import _make_config


class TestCreateBot:
    def test_creates_application(self):
        config = _make_config()
        with patch("slskd_importer.telegram.core.app.Application") as mock_app_cls:
            mock_builder = MagicMock()
            mock_app = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.post_init.return_value = mock_builder
            mock_builder.post_shutdown.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            app = create_bot(config)
            assert app is mock_app
            mock_app.add_handler.assert_called()
            # 8 command handlers (/start+/help share one) + callback + text message
            assert mock_app.add_handler.call_count == 10
            mock_builder.base_url.assert_not_called()
            mock_builder.post_shutdown.assert_called_once()

    def test_local_bot_api_server_wiring(self):
        config = _make_config()
        config.telegram_api_base_url = "http://telegram-bot-api:8081"
        with patch("slskd_importer.telegram.core.app.Application") as mock_app_cls:
            mock_builder = MagicMock()
            mock_app = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.post_init.return_value = mock_builder
            mock_builder.post_shutdown.return_value = mock_builder
            mock_builder.base_url.return_value = mock_builder
            mock_builder.base_file_url.return_value = mock_builder
            mock_builder.local_mode.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            app = create_bot(config)
            assert app is mock_app
            mock_builder.base_url.assert_called_once_with("http://telegram-bot-api:8081/bot")
            mock_builder.base_file_url.assert_called_once_with("http://telegram-bot-api:8081/file/bot")
            mock_builder.local_mode.assert_called_once_with(True)

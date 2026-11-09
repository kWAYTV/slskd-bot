"""PTB application wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from slskd_importer.telegram.core.app import create_bot
from tests.telegram.download.helpers import _make_config

# Every fluent ApplicationBuilder call create_bot chains before build().
_CHAINED = (
    "token",
    "post_init",
    "post_shutdown",
    "connect_timeout",
    "read_timeout",
    "write_timeout",
    "media_write_timeout",
    "pool_timeout",
    "base_url",
    "base_file_url",
    "local_mode",
)


def _fluent_builder(mock_app):
    mock_builder = MagicMock()
    for name in _CHAINED:
        getattr(mock_builder, name).return_value = mock_builder
    mock_builder.build.return_value = mock_app
    return mock_builder


class TestCreateBot:
    def test_creates_application(self):
        config = _make_config()
        with patch("slskd_importer.telegram.core.app.Application") as mock_app_cls:
            mock_app = MagicMock()
            mock_builder = _fluent_builder(mock_app)
            mock_app_cls.builder.return_value = mock_builder

            app = create_bot(config)
            assert app is mock_app
            mock_app.add_handler.assert_called()
            # command handlers (/start+/help and /lang+/language share) + sweep + callback + text
            assert mock_app.add_handler.call_count == 11
            mock_builder.base_url.assert_not_called()
            mock_builder.post_shutdown.assert_called_once()

    def test_local_bot_api_server_wiring(self):
        config = _make_config()
        config.telegram_api_base_url = "http://telegram-bot-api:8081"
        with patch("slskd_importer.telegram.core.app.Application") as mock_app_cls:
            mock_app = MagicMock()
            mock_builder = _fluent_builder(mock_app)
            mock_app_cls.builder.return_value = mock_builder

            app = create_bot(config)
            assert app is mock_app
            mock_builder.base_url.assert_called_once_with("http://telegram-bot-api:8081/bot")
            mock_builder.base_file_url.assert_called_once_with("http://telegram-bot-api:8081/file/bot")
            mock_builder.local_mode.assert_called_once_with(True)

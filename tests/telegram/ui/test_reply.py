"""Reply-to grouping helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import ReplyParameters

from slskd_importer.telegram.ui.reply import collapse_status_message, reply_kwargs


class TestReplyKwargs:
    def test_missing_id_is_empty(self):
        assert reply_kwargs(None) == {}

    def test_quotes_parent(self):
        kwargs = reply_kwargs(42)
        params = kwargs["reply_parameters"]
        assert isinstance(params, ReplyParameters)
        assert params.message_id == 42
        assert params.allow_sending_without_reply is True


class TestCollapseStatusMessage:
    @pytest.mark.asyncio
    async def test_deletes_progress_message(self):
        bot = MagicMock()
        bot.delete_message = AsyncMock()
        await collapse_status_message(bot, 1, 99)
        bot.delete_message.assert_awaited_once_with(chat_id=1, message_id=99)

    @pytest.mark.asyncio
    async def test_falls_back_to_edit(self):
        bot = MagicMock()
        bot.delete_message = AsyncMock(side_effect=Exception("too old"))
        bot.edit_message_text = AsyncMock()
        await collapse_status_message(bot, 1, 99, fallback="below")
        bot.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_without_id(self):
        bot = MagicMock()
        bot.delete_message = AsyncMock()
        await collapse_status_message(bot, 1, None)
        bot.delete_message.assert_not_called()

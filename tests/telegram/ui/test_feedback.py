"""Reactions, chat actions and pins never raise and skip missing ids."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import ReactionTypeEmoji
from telegram.constants import ChatAction
from telegram.error import BadRequest

from slskd_importer.telegram.ui import feedback


@pytest.mark.asyncio
async def test_react_sets_emoji_and_clears_with_none():
    bot = MagicMock()
    bot.set_message_reaction = AsyncMock()
    await feedback.react(bot, 1, 9, feedback.REACTION_SAVED)
    bot.set_message_reaction.assert_awaited_once_with(chat_id=1, message_id=9, reaction=[ReactionTypeEmoji("👍")])
    await feedback.react(bot, 1, 9, None)
    assert bot.set_message_reaction.await_args.kwargs["reaction"] == []


@pytest.mark.asyncio
async def test_react_skips_missing_message_and_swallows_errors():
    bot = MagicMock()
    bot.set_message_reaction = AsyncMock(side_effect=BadRequest("reactions disabled"))
    await feedback.react(bot, 1, None, "👀")
    bot.set_message_reaction.assert_not_called()
    await feedback.react(bot, 1, 5, "👀")  # must not raise


@pytest.mark.asyncio
async def test_chat_actions():
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    await feedback.show_typing(bot, 1)
    await feedback.show_uploading(bot, 1)
    actions = [c.kwargs["action"] for c in bot.send_chat_action.await_args_list]
    assert actions == [ChatAction.TYPING, ChatAction.UPLOAD_DOCUMENT]


@pytest.mark.asyncio
async def test_pin_unpin():
    bot = MagicMock()
    bot.pin_chat_message = AsyncMock(side_effect=BadRequest("not enough rights"))
    bot.unpin_chat_message = AsyncMock()
    await feedback.pin(bot, 1, 3)  # error swallowed
    await feedback.pin(bot, 1, None)
    bot.pin_chat_message.assert_awaited_once_with(chat_id=1, message_id=3, disable_notification=True)
    await feedback.unpin(bot, 1, 3)
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=1, message_id=3)

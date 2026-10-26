"""Sweep review callbacks edit audio captions, not text."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.records.sweep_models import DECISION_TAKE_NEW, Review
from slskd_importer.telegram.library_sweep import callbacks


@pytest.mark.asyncio
async def test_take_new_edits_caption():
    bot = MagicMock()
    bot.sweep.users = {1}
    bot._can_save_library = MagicMock(return_value=True)
    review = Review(
        id=7,
        stem="Artist - Title",
        current_path="/music/Artist - Title.flac",
        proposal_path="/music/.sweep-review/Artist - Title.flac.sweep",
        proposal_ext="flac",
        both_name="Artist - Title (hi-res).flac",
        reason="same and better",
        current_desc="flac",
        proposal_desc="flac 24/96",
    )
    bot.sweep.decide = AsyncMock(return_value=(review, "/music/Artist - Title.flac"))

    query = AsyncMock()
    query.from_user.id = 1
    query.edit_message_caption = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch(
        "slskd_importer.telegram.library_sweep.callbacks.edit_approval_message",
        new_callable=AsyncMock,
    ) as edit:
        await callbacks.handle_sweep_decision(bot, update, MagicMock(), 1, "swp:7:n")

    bot.sweep.decide.assert_awaited_once_with(7, DECISION_TAKE_NEW)
    edit.assert_awaited_once()
    assert "Took the new copy" in edit.await_args.args[1]
    assert "Artist - Title.flac" in edit.await_args.args[1]

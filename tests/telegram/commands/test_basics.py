"""Command menu and bot description registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from slskd_importer.telegram.commands.basics import register_bot_commands
from slskd_importer.telegram.i18n import LOCALES, t


@pytest.mark.asyncio
async def test_registers_commands_and_descriptions_per_locale():
    app = MagicMock()
    app.bot = AsyncMock()
    await register_bot_commands(app)

    # Default (no language_code) plus one per non-English locale.
    assert app.bot.set_my_commands.await_count == len(LOCALES)
    codes = [c.kwargs.get("language_code") for c in app.bot.set_my_description.await_args_list]
    assert codes == [None, "es", "gl", "de"]
    first = app.bot.set_my_description.await_args_list[0].args[0]
    assert first == t("en", "bot_description")
    assert app.bot.set_my_short_description.await_count == len(LOCALES)
    for call in app.bot.set_my_short_description.await_args_list:
        assert len(call.args[0]) <= 120
    for call in app.bot.set_my_description.await_args_list:
        assert len(call.args[0]) <= 512


@pytest.mark.asyncio
async def test_description_failure_does_not_break_startup():
    app = MagicMock()
    app.bot = AsyncMock()
    app.bot.set_my_description = AsyncMock(side_effect=BadRequest("flood"))
    await register_bot_commands(app)  # must not raise
    assert app.bot.set_my_commands.await_count == len(LOCALES)

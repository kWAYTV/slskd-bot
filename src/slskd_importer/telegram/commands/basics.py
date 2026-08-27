"""/start and /help — the welcome card, plus the command menu."""

from __future__ import annotations

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.commands.keyboards import build_language_keyboard
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, LOCALES, normalize_locale, t


def _commands_for(locale: str) -> list[BotCommand]:
    return [
        BotCommand("start", t(locale, "cmd_start")),
        BotCommand("help", t(locale, "cmd_help")),
        BotCommand("lang", t(locale, "cmd_lang")),
        BotCommand("status", t(locale, "cmd_status")),
        BotCommand("history", t(locale, "cmd_history")),
        BotCommand("stats", t(locale, "cmd_stats")),
        BotCommand("undo", t(locale, "cmd_undo")),
        BotCommand("import", t(locale, "cmd_import")),
        BotCommand("cancel", t(locale, "cmd_cancel")),
    ]


async def register_bot_commands(application) -> None:
    await application.bot.set_my_commands(_commands_for(DEFAULT_LOCALE))
    for locale in LOCALES:
        if locale == DEFAULT_LOCALE:
            continue
        await application.bot.set_my_commands(_commands_for(locale), language_code=locale)


async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /help — language picker on first chat, welcome after."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    if not self.has_locale(chat_id):
        prompt = normalize_locale(getattr(update.effective_user, "language_code", None))
        await update.message.reply_text(
            t(prompt, "lang_pick"),
            reply_markup=build_language_keyboard(),
        )
        return

    await update.message.reply_text(
        self.t(chat_id, "welcome"),
        parse_mode=ParseMode.MARKDOWN,
    )

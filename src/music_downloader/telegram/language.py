"""First-time language pick and /lang — GNU gettext catalogs, persisted per user."""

from __future__ import annotations

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationHandlerStop, ContextTypes

from music_downloader.i18n.catalog import DEFAULT_LOCALE, SUPPORTED_LOCALES, gettext, negotiate_locale, set_locale
from music_downloader.telegram.messages import welcome_text

_ = gettext

# Shown before a locale exists — every supported language, native names on the buttons.
FIRST_TIME_PROMPT = "Choose your language\nElige tu idioma\nWähle deine Sprache\nEscolle o teu idioma"


def build_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(name, callback_data=f"lang:{code}")] for code, name in SUPPORTED_LOCALES.items()]
    )


def bot_commands() -> list[tuple[str | None, list[BotCommand]]]:
    """Default (English) command list plus one set per Telegram language_code."""
    descriptions = {
        "en": {
            "start": "How to search and download",
            "help": "Show help",
            "lang": "Change language",
            "auto": "Toggle auto-download",
            "quality": "Prefer CD or Hi-Res audio",
            "status": "Active searches and downloads",
            "history": "Recent downloads",
            "undo": "Remove the last saved track",
            "import": "Import a Spotify playlist or album",
            "cancel": "Cancel the current operation",
        },
        "es": {
            "start": "Cómo buscar y descargar",
            "help": "Mostrar ayuda",
            "lang": "Cambiar idioma",
            "auto": "Activar o desactivar la descarga automática",
            "quality": "Preferir audio CD o Hi-Res",
            "status": "Búsquedas y descargas activas",
            "history": "Descargas recientes",
            "undo": "Eliminar la última pista guardada",
            "import": "Importar una playlist o álbum de Spotify",
            "cancel": "Cancelar la operación actual",
        },
        "de": {
            "start": "So suchst und lädst du herunter",
            "help": "Hilfe anzeigen",
            "lang": "Sprache ändern",
            "auto": "Automatischen Download umschalten",
            "quality": "CD- oder Hi-Res-Audio bevorzugen",
            "status": "Aktive Suchen und Downloads",
            "history": "Letzte Downloads",
            "undo": "Zuletzt gespeicherten Titel entfernen",
            "import": "Spotify-Playlist oder -Album importieren",
            "cancel": "Aktuellen Vorgang abbrechen",
        },
        "gl": {
            "start": "Como buscar e descargar",
            "help": "Amosar a axuda",
            "lang": "Cambiar o idioma",
            "auto": "Activar ou desactivar a descarga automática",
            "quality": "Preferir audio CD ou Hi-Res",
            "status": "Buscas e descargas activas",
            "history": "Descargas recentes",
            "undo": "Eliminar a última pista gardada",
            "import": "Importar unha playlist ou álbum de Spotify",
            "cancel": "Cancelar a operación actual",
        },
    }
    names = ("start", "help", "lang", "auto", "quality", "status", "history", "undo", "import", "cancel")
    packs: list[tuple[str | None, list[BotCommand]]] = []
    for code, texts in descriptions.items():
        commands = [BotCommand(name, texts[name]) for name in names]
        packs.append((None if code == DEFAULT_LOCALE else code, commands))
    return packs


async def register_bot_commands(application) -> None:
    for language_code, commands in bot_commands():
        await application.bot.set_my_commands(commands, language_code=language_code)


async def prompt_language(update: Update, first_time: bool) -> None:
    text = FIRST_TIME_PROMPT if first_time else _("Choose a language:")
    markup = build_language_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
        return
    if update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def ensure_locale(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Group -1 gate: apply stored locale, or stop and ask on first use."""
    user = update.effective_user
    if user is None:
        return

    query = update.callback_query
    if query and query.data and query.data.startswith("lang:"):
        await apply_language_choice(self, update, context)
        raise ApplicationHandlerStop

    locale = self.locale_store.get(user.id)
    if locale:
        set_locale(locale)
        return

    if not self._is_authorized(user.id):
        set_locale(negotiate_locale(user.language_code))
        return

    set_locale(negotiate_locale(user.language_code))
    await prompt_language(update, first_time=True)
    raise ApplicationHandlerStop


async def apply_language_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return

    if not self._is_authorized(user.id):
        await query.answer()
        return

    chosen = query.data.split(":", 1)[1]
    if chosen not in SUPPORTED_LOCALES:
        await query.answer()
        return

    first_time = self.locale_store.get(user.id) is None
    locale = self.locale_store.set(user.id, chosen)
    set_locale(locale)
    await query.answer()
    await query.edit_message_text(
        _("Language set to {name}.").format(name=SUPPORTED_LOCALES[locale]),
    )
    if first_time and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=welcome_text(),
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_lang(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await self._check_auth(update):
        return
    await prompt_language(update, first_time=False)

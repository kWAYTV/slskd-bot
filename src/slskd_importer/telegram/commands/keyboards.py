"""Inline keyboards for slash-command surfaces: language, history."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.telegram.i18n import LABELS, LOCALES


def build_language_keyboard() -> InlineKeyboardMarkup:
    """Language picker — labels stay in the native language of each option."""
    buttons = [
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[:2]],
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[2:]],
    ]
    return InlineKeyboardMarkup(buttons)


def build_history_keyboard(records) -> InlineKeyboardMarkup | None:
    """Per-row undo buttons for successful history entries."""
    buttons = []
    for entry in records:
        if entry.status != "success":
            continue
        label = f"↩️ {entry.filename}"
        if len(label) > 64:
            label = label[:61] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"hu:{entry.id}")])
    return InlineKeyboardMarkup(buttons) if buttons else None

"""Inline keyboards for slash-command surfaces: language, quality, history."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.telegram.i18n import DEFAULT_LOCALE, LABELS, LOCALES, t


def build_language_keyboard() -> InlineKeyboardMarkup:
    """Language picker — labels stay in the native language of each option."""
    buttons = [
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[:2]],
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[2:]],
    ]
    return InlineKeyboardMarkup(buttons)


def build_quality_keyboard(current: str, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Build keyboard to switch the audio quality preference."""
    if current == "cd":
        return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_quality_hires"), callback_data="qp:hires")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_quality_cd"), callback_data="qp:cd")]])


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

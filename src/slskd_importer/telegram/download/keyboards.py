"""Inline keyboards for download approval and retry."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.telegram.i18n import DEFAULT_LOCALE, t


def build_approve_keyboard(
    download_id: str, has_next: bool = False, *, locale: str = DEFAULT_LOCALE
) -> InlineKeyboardMarkup:
    """Build approve/reject keyboard for a downloaded file."""
    rows = [
        [
            InlineKeyboardButton(t(locale, "btn_save"), callback_data=f"approve:{download_id}"),
            InlineKeyboardButton(t(locale, "btn_discard"), callback_data=f"reject:{download_id}"),
        ]
    ]
    if has_next:
        rows.append([InlineKeyboardButton(t(locale, "btn_next_result"), callback_data=f"next:{download_id}")])
    return InlineKeyboardMarkup(rows)


def build_retry_keyboard(dl_id: str, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Retry button shown on download failure."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_retry"), callback_data=f"retry:{dl_id}")]])


def build_retry_next_keyboard(dl_id: str, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Retry + next result buttons shown after repeated failure."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(locale, "btn_retry"), callback_data=f"retry:{dl_id}"),
                InlineKeyboardButton(t(locale, "btn_next_result"), callback_data=f"next:{dl_id}"),
            ]
        ]
    )

"""Inline keyboards for playlist/album import."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.telegram.i18n import DEFAULT_LOCALE, t


def build_import_summary_keyboard(
    job_id: int, failed_count: int, *, locale: str = DEFAULT_LOCALE
) -> InlineKeyboardMarkup:
    """Retry-failed button on the end-of-import summary."""
    key = "btn_retry_failed_one" if failed_count == 1 else "btn_retry_failed_many"
    label = t(locale, key, n=failed_count)
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"if:{job_id}")]])


def build_import_confirm_keyboard(job_id: int, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Confirm/cancel keyboard for playlist import."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(locale, "btn_start_import"), callback_data=f"ic:{job_id}"),
                InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"ix:{job_id}"),
            ]
        ]
    )


def build_import_track_keyboard(
    job_id: int, track_id: int, dl_id: str, *, locale: str = DEFAULT_LOCALE
) -> InlineKeyboardMarkup:
    """Approve/reject/skip keyboard for individual import track downloads."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(locale, "btn_save"), callback_data=f"ia:{job_id}:{track_id}:{dl_id}"),
                InlineKeyboardButton(t(locale, "btn_discard"), callback_data=f"ir:{job_id}:{track_id}"),
            ],
            [
                InlineKeyboardButton(t(locale, "btn_skip"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )


def build_import_skip_keyboard(job_id: int, track_id: int, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Reject/skip keyboard for import tracks with no download available."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(locale, "btn_mark_failed"), callback_data=f"ir:{job_id}:{track_id}"),
                InlineKeyboardButton(t(locale, "btn_skip"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )


def build_import_failure_keyboard(
    job_id: int, track_id: int, dl_id: str, *, locale: str = DEFAULT_LOCALE
) -> InlineKeyboardMarkup:
    """Retry / skip / fail keyboard when an import download fails."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(locale, "btn_retry"), callback_data=f"iy:{job_id}:{track_id}:{dl_id}")],
            [
                InlineKeyboardButton(t(locale, "btn_mark_failed"), callback_data=f"ir:{job_id}:{track_id}"),
                InlineKeyboardButton(t(locale, "btn_skip"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )

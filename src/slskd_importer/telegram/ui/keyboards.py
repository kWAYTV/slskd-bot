"""Inline keyboard builders for Telegram conversations."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, LABELS, LOCALES, t


def build_language_keyboard() -> InlineKeyboardMarkup:
    """Language picker — labels stay in the native language of each option."""
    buttons = [
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[:2]],
        [InlineKeyboardButton(LABELS[code], callback_data=f"lang:{code}") for code in LOCALES[2:]],
    ]
    return InlineKeyboardMarkup(buttons)


def build_results_keyboard(
    results: list[SearchResult],
    page: int = 0,
    page_size: int = 10,
    *,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with search results for the user to pick from."""
    start = page * page_size
    end = min(start + page_size, len(results))
    page_results = results[start:end]

    buttons = []
    for i, result in enumerate(page_results):
        absolute_idx = start + i
        label = f"#{absolute_idx + 1} {result.duration_display} | {result.quality_display} | {result.size_mb:.0f}MB"
        buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{absolute_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(t(locale, "btn_prev"), callback_data=f"dl_page:{page - 1}"))
    if end < len(results):
        nav_row.append(InlineKeyboardButton(t(locale, "btn_next"), callback_data=f"dl_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    action_row = []
    if results:
        action_row.append(InlineKeyboardButton(t(locale, "btn_auto"), callback_data="dl:auto"))
    action_row.append(InlineKeyboardButton(t(locale, "btn_cancel"), callback_data="dl:cancel"))
    buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


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


def build_spotify_keyboard(
    tracks: list[TrackInfo],
    page: int = 0,
    page_size: int = 5,
    *,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for selecting from multiple Spotify results."""
    start = page * page_size
    end = min(start + page_size, len(tracks))
    page_tracks = tracks[start:end]

    buttons = []
    for i, item in enumerate(page_tracks):
        absolute_idx = start + i
        label = f"#{absolute_idx + 1} {item.artist} - {item.title} ({item.duration_display})"
        if len(label) > 64:
            label = label[:61] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"sp:{absolute_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(t(locale, "btn_prev"), callback_data=f"sp_page:{page - 1}"))
    if end < len(tracks):
        nav_row.append(InlineKeyboardButton(t(locale, "btn_next"), callback_data=f"sp_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(t(locale, "btn_direct"), callback_data="direct:search")])
    buttons.append([InlineKeyboardButton(t(locale, "btn_cancel"), callback_data="sp:cancel")])
    return InlineKeyboardMarkup(buttons)


def build_quality_keyboard(current: str, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Build keyboard to switch the audio quality preference."""
    if current == "cd":
        return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_quality_hires"), callback_data="qp:hires")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_quality_cd"), callback_data="qp:cd")]])


def build_import_summary_keyboard(
    job_id: int, failed_count: int, *, locale: str = DEFAULT_LOCALE
) -> InlineKeyboardMarkup:
    """Retry-failed button on the end-of-import summary."""
    key = "btn_retry_failed_one" if failed_count == 1 else "btn_retry_failed_many"
    label = t(locale, key, n=failed_count)
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"if:{job_id}")]])


def build_direct_search_keyboard(*, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Button to search Soulseek directly without Spotify resolution."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_direct"), callback_data="direct:search")]])


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

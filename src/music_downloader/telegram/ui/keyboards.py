"""Inline keyboard builders for Telegram conversations."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.i18n.catalog import ngettext
from music_downloader.soulseek.result import SearchResult


def build_results_keyboard(
    results: list[SearchResult],
    page: int = 0,
    page_size: int = 10,
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
        nav_row.append(InlineKeyboardButton(_("◀️ Prev"), callback_data=f"dl_page:{page - 1}"))
    if end < len(results):
        nav_row.append(InlineKeyboardButton(_("Next ▶️"), callback_data=f"dl_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    action_row = []
    if results:
        action_row.append(InlineKeyboardButton(_("Auto-pick best"), callback_data="dl:auto"))
    action_row.append(InlineKeyboardButton(_("Cancel"), callback_data="dl:cancel"))
    buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


def build_approve_keyboard(download_id: str, has_next: bool = False) -> InlineKeyboardMarkup:
    """Build approve/reject keyboard for a downloaded file."""
    rows = [
        [
            InlineKeyboardButton(_("💾 Save to library"), callback_data=f"approve:{download_id}"),
            InlineKeyboardButton(_("🗑 Discard"), callback_data=f"reject:{download_id}"),
        ]
    ]
    if has_next:
        rows.append([InlineKeyboardButton(_("⏭ Try next result"), callback_data=f"next:{download_id}")])
    return InlineKeyboardMarkup(rows)


def build_duplicate_keyboard() -> InlineKeyboardMarkup:
    """Build Continue/Cancel keyboard for duplicate detection."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_("Continue anyway"), callback_data="dup:continue"),
                InlineKeyboardButton(_("Cancel"), callback_data="dup:cancel"),
            ]
        ]
    )


def build_spotify_keyboard(
    tracks: list[TrackInfo],
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for selecting from multiple Spotify results."""
    start = page * page_size
    end = min(start + page_size, len(tracks))
    page_tracks = tracks[start:end]

    buttons = []
    for i, t in enumerate(page_tracks):
        absolute_idx = start + i
        label = f"#{absolute_idx + 1} {t.artist} - {t.title} ({t.duration_display})"
        if len(label) > 64:
            label = label[:61] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"sp:{absolute_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(_("◀️ Prev"), callback_data=f"sp_page:{page - 1}"))
    if end < len(tracks):
        nav_row.append(InlineKeyboardButton(_("Next ▶️"), callback_data=f"sp_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(_("🔍 Search Soulseek directly"), callback_data="direct:search")])
    buttons.append([InlineKeyboardButton(_("Cancel"), callback_data="sp:cancel")])
    return InlineKeyboardMarkup(buttons)


def build_auto_mode_keyboard(current_mode: bool) -> InlineKeyboardMarkup:
    """Build keyboard to toggle auto mode."""
    if current_mode:
        return InlineKeyboardMarkup([[InlineKeyboardButton(_("Disable auto-mode"), callback_data="auto:off")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(_("Enable auto-mode"), callback_data="auto:on")]])


def build_quality_keyboard(current: str) -> InlineKeyboardMarkup:
    """Build keyboard to switch the audio quality preference."""
    if current == "cd":
        return InlineKeyboardMarkup([[InlineKeyboardButton(_("Prefer Hi-Res (24-bit)"), callback_data="qp:hires")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(_("Prefer CD quality (16/44.1)"), callback_data="qp:cd")]])


def build_import_summary_keyboard(job_id: int, failed_count: int) -> InlineKeyboardMarkup:
    """Retry-failed button on the end-of-import summary."""
    label = ngettext("🔄 Retry {n} failed track", "🔄 Retry {n} failed tracks", failed_count).format(n=failed_count)
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"if:{job_id}")]])


def build_direct_search_keyboard() -> InlineKeyboardMarkup:
    """Button to search Soulseek directly without Spotify resolution."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(_("🔍 Search Soulseek directly"), callback_data="direct:search")]]
    )


def build_import_confirm_keyboard(job_id: int) -> InlineKeyboardMarkup:
    """Confirm/cancel keyboard for playlist import."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_("✅ Start import"), callback_data=f"ic:{job_id}"),
                InlineKeyboardButton(_("❌ Cancel"), callback_data=f"ix:{job_id}"),
            ]
        ]
    )


def build_import_track_keyboard(job_id: int, track_id: int, dl_id: str) -> InlineKeyboardMarkup:
    """Approve/reject/skip keyboard for individual import track downloads."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_("💾 Save to library"), callback_data=f"ia:{job_id}:{track_id}:{dl_id}"),
                InlineKeyboardButton(_("🗑 Discard"), callback_data=f"ir:{job_id}:{track_id}"),
            ],
            [
                InlineKeyboardButton(_("⏭ Skip track"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )


def build_import_skip_keyboard(job_id: int, track_id: int) -> InlineKeyboardMarkup:
    """Reject/skip keyboard for import tracks with no download available."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_("🚫 Mark failed"), callback_data=f"ir:{job_id}:{track_id}"),
                InlineKeyboardButton(_("⏭ Skip track"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )


def build_import_failure_keyboard(job_id: int, track_id: int, dl_id: str) -> InlineKeyboardMarkup:
    """Retry / skip / fail keyboard when an import download fails."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_("🔄 Retry"), callback_data=f"iy:{job_id}:{track_id}:{dl_id}")],
            [
                InlineKeyboardButton(_("🚫 Mark failed"), callback_data=f"ir:{job_id}:{track_id}"),
                InlineKeyboardButton(_("⏭ Skip track"), callback_data=f"is:{job_id}:{track_id}"),
            ],
        ]
    )


def build_retry_keyboard(dl_id: str) -> InlineKeyboardMarkup:
    """Retry button shown on download failure."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(_("🔄 Retry"), callback_data=f"retry:{dl_id}")]])


def build_retry_next_keyboard(dl_id: str) -> InlineKeyboardMarkup:
    """Retry + next result buttons shown after repeated failure."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_("🔄 Retry"), callback_data=f"retry:{dl_id}"),
                InlineKeyboardButton(_("⏭ Try next result"), callback_data=f"next:{dl_id}"),
            ]
        ]
    )

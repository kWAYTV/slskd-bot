"""Inline keyboards for Spotify pick, Soulseek results, and direct search."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, t


def build_results_keyboard(
    results: list[SearchResult],
    page: int = 0,
    page_size: int = 10,
    *,
    search_id: str,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with search results for the user to pick from."""
    start = page * page_size
    end = min(start + page_size, len(results))
    page_results = results[start:end]

    buttons = []
    for i, result in enumerate(page_results):
        absolute_idx = start + i
        label = (
            f"#{absolute_idx + 1}  {result.duration_display}  ·  {result.quality_display}  ·  {result.size_mb:.0f} MB"
        )
        buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{search_id}:{absolute_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(t(locale, "btn_prev"), callback_data=f"dl_page:{search_id}:{page - 1}"))
    if end < len(results):
        nav_row.append(InlineKeyboardButton(t(locale, "btn_next"), callback_data=f"dl_page:{search_id}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    action_row = []
    if results:
        action_row.append(InlineKeyboardButton(t(locale, "btn_auto"), callback_data=f"dl:{search_id}:auto"))
    action_row.append(InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"dl:{search_id}:cancel"))
    buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


def build_spotify_keyboard(
    tracks: list[TrackInfo],
    page: int = 0,
    page_size: int = 5,
    *,
    search_id: str,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for selecting from multiple Spotify results."""
    start = page * page_size
    end = min(start + page_size, len(tracks))
    page_tracks = tracks[start:end]

    buttons = []
    for i, item in enumerate(page_tracks):
        absolute_idx = start + i
        label = f"#{absolute_idx + 1}  {item.artist} — {item.title}"
        if len(label) > 64:
            label = label[:61] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"sp:{search_id}:{absolute_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(t(locale, "btn_prev"), callback_data=f"sp_page:{search_id}:{page - 1}"))
    if end < len(tracks):
        nav_row.append(InlineKeyboardButton(t(locale, "btn_next"), callback_data=f"sp_page:{search_id}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(t(locale, "btn_direct"), callback_data=f"direct:{search_id}")])
    buttons.append([InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"sp:{search_id}:cancel")])
    return InlineKeyboardMarkup(buttons)


def build_results_status_keyboard(
    *,
    label: str,
    search_id: str,
    show_cancel: bool,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Locked results keyboard after a pick — identity + optional cancel."""
    if len(label) > 64:
        label = label[:61] + "..."
    rows = [[InlineKeyboardButton(label, callback_data=f"lock:{search_id}")]]
    if show_cancel:
        rows.append([InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"dl:{search_id}:cancel")])
    return InlineKeyboardMarkup(rows)


def build_direct_search_keyboard(search_id: str, *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    """Button to search Soulseek directly without Spotify resolution."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(locale, "btn_direct"), callback_data=f"direct:{search_id}")]])

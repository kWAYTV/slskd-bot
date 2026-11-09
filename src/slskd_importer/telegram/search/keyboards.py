"""Inline keyboards for Spotify pick, Soulseek results, and direct search."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, t

NUMBERS_PER_ROW = 5


def build_results_keyboard(
    results: list[SearchResult],
    page: int = 0,
    page_size: int = 10,
    *,
    search_id: str,
    locale: str = DEFAULT_LOCALE,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with search results for the user to pick from.

    The card text already lists format, length, quality and size per ``#n``,
    so the picks are a compact row of numbers (five per row) under it.
    """
    start = page * page_size
    end = min(start + page_size, len(results))

    buttons = []
    numbers = [InlineKeyboardButton(f"#{idx + 1}", callback_data=f"dl:{search_id}:{idx}") for idx in range(start, end)]
    for row_start in range(0, len(numbers), NUMBERS_PER_ROW):
        buttons.append(numbers[row_start : row_start + NUMBERS_PER_ROW])

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


_BUTTON_MAX = 64
_SEP = "  ·  "


def _pick_label(number: int, name: str, tail: str) -> str:
    """``#n  Name  ·  tail`` within Telegram's button limit; the name is what gets shortened."""
    prefix = f"#{number}  "
    if not tail:
        label = prefix + name
        return label if len(label) <= _BUTTON_MAX else label[: _BUTTON_MAX - 1] + "…"
    budget = _BUTTON_MAX - len(prefix) - len(_SEP) - len(tail)
    if len(name) > budget:
        name = name[: max(budget - 1, 8)].rstrip() + "…"
    return f"{prefix}{name}{_SEP}{tail}"


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

    # One artist across the whole list: drop it from every button so title, length and year fit.
    same_artist = len({t.artist.lower() for t in tracks}) == 1
    buttons = []
    for i, item in enumerate(page_tracks):
        absolute_idx = start + i
        name = item.title if same_artist else f"{item.artist} — {item.title}"
        tail = "  ·  ".join(p for p in (item.duration_display, item.year) if p)
        buttons.append(
            [
                InlineKeyboardButton(
                    _pick_label(absolute_idx + 1, name, tail), callback_data=f"sp:{search_id}:{absolute_idx}"
                )
            ]
        )

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

"""Telegram message helpers: Markdown escaping, safe edits, result formatting."""

import logging

from telegram import Message
from telegram.error import BadRequest, NetworkError, TimedOut

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult

logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    """Escape Markdown V1 special characters for safe display."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


async def safe_edit(msg: Message, text: str, **kwargs) -> bool:
    """Edit a Telegram message, swallowing common failures.

    Returns True on success, False if the edit failed (logged as warning).
    """
    try:
        await msg.edit_text(text, **kwargs)
        return True
    except BadRequest as exc:
        logger.warning(f"Telegram edit failed (BadRequest): {exc}")
        return False
    except TimedOut:
        logger.warning("Telegram edit timed out")
        return False
    except NetworkError as exc:
        logger.warning(f"Telegram edit network error: {exc}")
        return False


async def safe_query_edit(query, text: str, **kwargs) -> bool:
    """Edit a callback query message, swallowing transient Telegram errors."""
    try:
        await query.edit_message_text(text, **kwargs)
        return True
    except BadRequest as exc:
        logger.warning(f"Telegram query edit failed (BadRequest): {exc}")
        return False
    except TimedOut:
        logger.warning("Telegram query edit timed out")
        return False
    except NetworkError as exc:
        logger.warning(f"Telegram query edit network error: {exc}")
        return False


def format_spotify_results(tracks: list[TrackInfo], page: int = 0, page_size: int = 5) -> str:
    """Format Spotify track candidates for selection (one page)."""
    total = len(tracks)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = (total + page_size - 1) // page_size

    header = "🔍 *Multiple matches found on Spotify:*"
    if total_pages > 1:
        header += f" (page {page + 1}/{total_pages})"
    lines = [header + "\n"]

    for i in range(start, end):
        t = tracks[i]
        lines.append(
            f"*#{i + 1} {t.artist} - {t.title}*\n"
            f"    Album: {t.album} ({t.year}) | {t.duration_display}\n"
            f"    [Listen on Spotify]({t.spotify_url})"
        )
    lines.append("\nPick the correct version:")
    return "\n".join(lines)


def format_search_results(
    track: TrackInfo,
    results: list[SearchResult],
    is_fallback: bool = False,
    page: int = 0,
    page_size: int = 10,
) -> str:
    """Format Soulseek search results for display in Telegram (one page)."""
    total = len(results)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = (total + page_size - 1) // page_size

    is_direct = track.duration_ms == 0
    if is_direct:
        if track.artist:
            header = [
                f"🎵 *{track.artist} - {track.title}*\n",
                f"Found {total} FLAC matches:\n",
            ]
        else:
            header = [
                f"\U0001f50e *Direct search:* `{track.title}`\n",
                f"Found {total} FLAC matches:\n",
            ]
    elif is_fallback:
        header = [
            f"🎵 *{track.artist} - {track.title}*",
            f"Duration: {track.duration_display} | Album: {track.album}\n",
            f"⚠️ No FLAC found — showing all formats ({total} matches):\n",
        ]
    else:
        header = [
            f"🎵 *{track.artist} - {track.title}*",
            f"Duration: {track.duration_display} | Album: {track.album}\n",
            f"Found {total} FLAC matches:\n",
        ]

    if total_pages > 1:
        header.append(f"📄 Page {page + 1}/{total_pages}\n")

    lines = header
    for i in range(start, end):
        r = results[i]
        slot_icon = "🟢" if r.has_free_slot else "🔴"
        fmt = r.extension.upper()
        format_tag = f" [{fmt}]" if is_fallback else ""
        lines.append(
            f"*#{i + 1}* {slot_icon} `{r.duration_display}` | "
            f"{r.quality_display}{format_tag} | {r.size_mb:.0f}MB\n"
            f"    `{r.basename}`"
        )

    return "\n".join(lines)

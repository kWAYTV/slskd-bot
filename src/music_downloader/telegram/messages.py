"""Telegram message helpers: Markdown escaping, safe edits, result formatting."""

import logging

from telegram import Message
from telegram.error import BadRequest, NetworkError, TimedOut

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.i18n.catalog import ngettext
from music_downloader.library.flac import FlacVerdict
from music_downloader.soulseek.result import SearchResult

logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    """Escape Telegram legacy-Markdown (V1) special characters.

    V1 only honors backslash escapes for ``_ * ` [`` — escaping anything else
    renders the backslash literally (e.g. ``\\-`` shows up in the chat).
    """
    for ch in "_*`[":
        text = text.replace(ch, f"\\{ch}")
    return text


def md_code_safe(text: str) -> str:
    """Neutralize backticks in values interpolated into Markdown code spans."""
    return text.replace("`", "ʼ")


def code_span(text: str) -> str:
    """Wrap text in a Markdown code span, neutralizing backticks that would break it."""
    return f"`{md_code_safe(text)}`"


def progress_bar(percent: float, width: int = 10) -> str:
    """Render a text progress bar like ▰▰▰▱▱▱▱▱▱▱ for a 0-100 percent value."""
    clamped = max(0.0, min(100.0, percent))
    filled = round(clamped / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


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


def welcome_text() -> str:
    return _(
        "Send me a song name (e.g., `Nancy Sinatra Bang Bang`), a Spotify track link, "
        "or a SoundCloud track link and I'll find and download it in FLAC.\n\n"
        "Commands:\n"
        "/auto — Toggle auto-download mode\n"
        "/quality — Prefer CD or Hi-Res audio\n"
        "/import <url> — Import a Spotify playlist or album\n"
        "/import resume — Continue a paused import after restart\n"
        "/status — Show active searches, downloads, and imports\n"
        "/history — Recent downloads\n"
        "/undo — Remove the last track saved to the library\n"
        "/cancel — Cancel the current search, download, or import\n"
        "/lang — Change language\n"
        "/help — Show this message"
    )


def format_result_reasons(track: TrackInfo, result: SearchResult) -> str:
    """One-line 'why this match won' — duration closeness, source health, score.

    Quality (bit depth/sample rate) is omitted: callers already display it.
    """
    parts = []
    if track.duration_secs > 0 and result.length:
        diff = abs(result.length - track.duration_secs)
        parts.append(_("⏱ exact duration") if diff == 0 else _("⏱ ±{secs}s").format(secs=diff))
    if result.has_free_slot:
        parts.append(_("🟢 free slot"))
    elif result.queue_length:
        parts.append(_("🔴 queue of {n}").format(n=result.queue_length))
    if result.score:
        parts.append(_("⭐ {score}/100").format(score=f"{result.score:.0f}"))
    return " · ".join(parts)


def format_flac_verdict(verdict: FlacVerdict) -> str:
    """Localize a FLAC analysis line (domain `display` stays English)."""
    if verdict.verdict == "AUTHENTIC":
        return _("{emoji} Lossless OK (spectrum to {khz:.1f}kHz)").format(emoji=verdict.emoji, khz=verdict.cutoff_khz)
    labels = {
        "WARNING": _("Possible transcode"),
        "SUSPICIOUS": _("Likely transcode"),
        "FAKE": _("Fake lossless"),
    }
    label = labels.get(verdict.verdict, verdict.verdict)
    return _("{emoji} {label} (cutoff {khz:.1f}kHz)").format(emoji=verdict.emoji, label=label, khz=verdict.cutoff_khz)


def format_spotify_results(tracks: list[TrackInfo], page: int = 0, page_size: int = 5) -> str:
    """Format Spotify track candidates for selection (one page)."""
    total = len(tracks)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = (total + page_size - 1) // page_size

    header = _("🔍 *Multiple matches found on Spotify:*")
    if total_pages > 1:
        header += _(" (page {page}/{total})").format(page=page + 1, total=total_pages)
    lines = [header + "\n"]

    for i in range(start, end):
        t = tracks[i]
        lines.append(
            _(
                "*#{n} {artist} - {title}*\n    Album: {album} ({year}) | {duration}\n    [Listen on Spotify]({url})"
            ).format(
                n=i + 1,
                artist=escape_md(t.artist),
                title=escape_md(t.title),
                album=escape_md(t.album),
                year=escape_md(t.year),
                duration=t.duration_display,
                url=t.spotify_url,
            )
        )
    lines.append("\n" + _("Pick the correct version:"))
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

    artist = escape_md(track.artist)
    title = escape_md(track.title)
    album = escape_md(track.album)
    if is_fallback:
        matches = ngettext(
            "⚠️ No FLAC found — showing all formats ({n} match):",
            "⚠️ No FLAC found — showing all formats ({n} matches):",
            total,
        ).format(n=total)
    else:
        matches = ngettext("Found {n} FLAC match:", "Found {n} FLAC matches:", total).format(n=total)
    is_direct = track.duration_ms == 0
    if is_direct:
        if track.artist:
            header = [
                f"🎵 *{artist} - {title}*\n",
                matches + "\n",
            ]
        else:
            header = [
                _("🔍 *Direct search:* `{query}`").format(query=track.title) + "\n",
                matches + "\n",
            ]
    else:
        header = [
            f"🎵 *{artist} - {title}*",
            _("Duration: {duration} | Album: {album}").format(duration=track.duration_display, album=album) + "\n",
            matches + "\n",
        ]

    if total_pages > 1:
        header.append(_("📄 Page {page}/{total}").format(page=page + 1, total=total_pages) + "\n")

    lines = header
    for i in range(start, end):
        r = results[i]
        slot_icon = "🟢" if r.has_free_slot else "🔴"
        fmt = r.extension.upper()
        format_tag = f" [{fmt}]" if is_fallback else ""
        lines.append(
            f"*#{i + 1}* {slot_icon} `{r.duration_display}` | "
            f"{r.quality_display}{format_tag} | {r.size_mb:.0f}MB\n"
            f"    {code_span(r.basename)}"
        )

    return "\n".join(lines)

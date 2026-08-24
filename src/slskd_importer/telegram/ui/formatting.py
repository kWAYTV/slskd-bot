"""Text content for Telegram messages: welcome, progress, result formatting."""

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.library.flac import FlacVerdict
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.ui.markdown import code_span, escape_md


def progress_bar(percent: float, width: int = 10) -> str:
    """Render a text progress bar like ▰▰▰▱▱▱▱▱▱▱ for a 0-100 percent value."""
    clamped = max(0.0, min(100.0, percent))
    filled = round(clamped / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def track_md(track: TrackInfo) -> str:
    """Bold, escaped ``Artist - Title`` fragment."""
    return f"*{escape_md(track.artist)} - {escape_md(track.title)}*"


def welcome_text() -> str:
    return (
        "Send me a song name (e.g., `Nancy Sinatra Bang Bang`) or a Spotify track link "
        "and I'll find and download it in FLAC.\n\n"
        "Commands:\n"
        "/quality — Prefer CD or Hi-Res audio\n"
        "/import <url> — Import a Spotify playlist or album\n"
        "/import resume — Continue a paused import after restart\n"
        "/status — Show active searches, downloads, and imports\n"
        "/history — Recent downloads (tap ↩️ to remove one)\n"
        "/stats — Library and download stats\n"
        "/undo — Remove the last track saved to the library\n"
        "/cancel — Cancel the current search, download, or import\n"
        "/help — Show this message"
    )


def format_result_reasons(track: TrackInfo, result: SearchResult) -> str:
    """One-line 'why this match won' — duration closeness, source health, score.

    Quality (bit depth/sample rate) is omitted: callers already display it.
    """
    parts = []
    if track.duration_secs > 0 and result.length:
        diff = abs(result.length - track.duration_secs)
        parts.append(("⏱ exact duration") if diff == 0 else (f"⏱ ±{diff}s"))
    if result.has_free_slot:
        parts.append("🟢 free slot")
    elif result.queue_length:
        parts.append(f"🔴 queue of {result.queue_length}")
    if result.score:
        parts.append(("⭐ {score}/100").format(score=f"{result.score:.0f}"))
    return " · ".join(parts)


def format_flac_verdict(verdict: FlacVerdict) -> str:
    """Localize a FLAC analysis line (domain `display` stays English)."""
    if verdict.verdict == "AUTHENTIC":
        return f"{verdict.emoji} Lossless OK (spectrum to {verdict.cutoff_khz:.1f}kHz)"
    labels = {
        "WARNING": ("Possible transcode"),
        "SUSPICIOUS": ("Likely transcode"),
        "FAKE": ("Fake lossless"),
    }
    label = labels.get(verdict.verdict, verdict.verdict)
    return f"{verdict.emoji} {label} (cutoff {verdict.cutoff_khz:.1f}kHz)"


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
            f"*#{i + 1} {escape_md(t.artist)} - {escape_md(t.title)}*\n    Album: {escape_md(t.album)} ({escape_md(t.year)}) | {t.duration_display}\n    [Listen on Spotify]({t.spotify_url})"
        )
    lines.append("\n" + ("Pick the correct version:"))
    return "\n".join(lines)


def _results_header(track: TrackInfo, total: int, is_fallback: bool) -> list[str]:
    """Header lines for a Soulseek result list: track identity + match count."""
    matches = _match_count_line(total, is_fallback)
    artist = escape_md(track.artist)
    title = escape_md(track.title)

    is_direct = track.duration_ms == 0
    if not is_direct:
        album_line = f"Duration: {track.duration_display} | Album: {escape_md(track.album)}"
        return [f"🎵 *{artist} - {title}*", album_line + "\n", matches + "\n"]

    if track.artist:
        return [f"🎵 *{artist} - {title}*\n", matches + "\n"]
    return [(f"🔍 *Direct search:* `{track.title}`") + "\n", matches + "\n"]


def _match_count_line(total: int, is_fallback: bool) -> str:
    noun = "match" if total == 1 else "matches"
    if is_fallback:
        return f"⚠️ No FLAC found — showing all formats ({total} {noun}):"
    return f"Found {total} FLAC {noun}:"


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

    lines = _results_header(track, total, is_fallback)
    if total_pages > 1:
        lines.append((f"📄 Page {page + 1}/{total_pages}") + "\n")
    for i in range(start, end):
        r = results[i]
        slot_icon = "🟢" if r.has_free_slot else "🔴"
        fmt = r.extension.upper()
        format_tag = f" [{fmt}]" if is_fallback else ""
        folder = r.parent_dir
        folder_line = f"\n    _{escape_md(folder)}_" if folder else ""
        lines.append(
            f"*#{i + 1}* {slot_icon} `{r.duration_display}` | "
            f"{r.quality_display}{format_tag} | {r.size_mb:.0f}MB\n"
            f"    {code_span(r.basename)}{folder_line}"
        )

    return "\n".join(lines)

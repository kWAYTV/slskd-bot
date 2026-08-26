"""Text content for Telegram messages: welcome, progress, result formatting."""

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.library.flac import FlacVerdict
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, t
from slskd_importer.telegram.ui.markdown import code_span, escape_md


def progress_bar(percent: float, width: int = 10) -> str:
    """Render a text progress bar like ▰▰▰▱▱▱▱▱▱▱ for a 0-100 percent value."""
    clamped = max(0.0, min(100.0, percent))
    filled = round(clamped / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def track_md(track: TrackInfo) -> str:
    """Bold, escaped ``Artist - Title`` fragment."""
    return f"*{escape_md(track.artist)} - {escape_md(track.title)}*"


def welcome_text(locale: str = DEFAULT_LOCALE) -> str:
    return t(locale, "welcome")


def format_result_reasons(track: TrackInfo, result: SearchResult, locale: str = DEFAULT_LOCALE) -> str:
    """One-line 'why this match won' — duration closeness, source health, score.

    Quality (bit depth/sample rate) is omitted: callers already display it.
    """
    parts = []
    if track.duration_secs > 0 and result.length:
        diff = abs(result.length - track.duration_secs)
        parts.append(t(locale, "reason_exact") if diff == 0 else t(locale, "reason_diff", diff=diff))
    if result.has_free_slot:
        parts.append(t(locale, "reason_slot"))
    elif result.queue_length:
        parts.append(t(locale, "reason_queue", n=result.queue_length))
    if result.score:
        parts.append(t(locale, "reason_score", score=f"{result.score:.0f}"))
    return " · ".join(parts)


def format_flac_verdict(verdict: FlacVerdict, locale: str = DEFAULT_LOCALE) -> str:
    """Localize a FLAC analysis line (domain `display` stays English)."""
    if verdict.verdict == "AUTHENTIC":
        return t(locale, "flac_ok", emoji=verdict.emoji, khz=f"{verdict.cutoff_khz:.1f}")
    labels = {
        "WARNING": t(locale, "flac_warning"),
        "SUSPICIOUS": t(locale, "flac_suspicious"),
        "FAKE": t(locale, "flac_fake"),
    }
    label = labels.get(verdict.verdict, verdict.verdict)
    return t(locale, "flac_cutoff", emoji=verdict.emoji, label=label, khz=f"{verdict.cutoff_khz:.1f}")


def format_spotify_results(
    tracks: list[TrackInfo], page: int = 0, page_size: int = 5, locale: str = DEFAULT_LOCALE
) -> str:
    """Format Spotify track candidates for selection (one page)."""
    total = len(tracks)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = (total + page_size - 1) // page_size

    header = t(locale, "spotify_header")
    if total_pages > 1:
        header += t(locale, "spotify_page", page=page + 1, pages=total_pages)
    lines = [header + "\n"]

    for i in range(start, end):
        item = tracks[i]
        lines.append(
            f"*#{i + 1} {escape_md(item.artist)} - {escape_md(item.title)}*\n"
            + t(
                locale,
                "spotify_album_line",
                album=escape_md(item.album),
                year=escape_md(item.year),
                duration=item.duration_display,
            )
            + "\n"
            + t(locale, "spotify_listen", url=item.spotify_url)
        )
    lines.append("\n" + t(locale, "spotify_pick"))
    return "\n".join(lines)


def _results_header(track: TrackInfo, total: int, is_fallback: bool, locale: str) -> list[str]:
    """Header lines for a Soulseek result list: track identity + match count."""
    matches = _match_count_line(total, is_fallback, locale)
    artist = escape_md(track.artist)
    title = escape_md(track.title)

    is_direct = track.duration_ms == 0
    if not is_direct:
        album_line = t(locale, "results_duration_album", duration=track.duration_display, album=escape_md(track.album))
        return [f"🎵 *{artist} - {title}*", album_line + "\n", matches + "\n"]

    if track.artist:
        return [f"🎵 *{artist} - {title}*\n", matches + "\n"]
    return [t(locale, "direct_header", title=track.title) + "\n", matches + "\n"]


def _match_count_line(total: int, is_fallback: bool, locale: str) -> str:
    noun = t(locale, "noun_match") if total == 1 else t(locale, "noun_matches")
    if is_fallback:
        return t(locale, "results_no_flac", total=total, noun=noun)
    return t(locale, "results_flac", total=total, noun=noun)


def format_search_results(
    track: TrackInfo,
    results: list[SearchResult],
    is_fallback: bool = False,
    page: int = 0,
    page_size: int = 10,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Format Soulseek search results for display in Telegram (one page)."""
    total = len(results)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = (total + page_size - 1) // page_size

    lines = _results_header(track, total, is_fallback, locale)
    if total_pages > 1:
        lines.append(t(locale, "results_page", page=page + 1, pages=total_pages) + "\n")
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

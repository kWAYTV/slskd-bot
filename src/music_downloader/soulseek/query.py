"""Soulseek search-query construction.

Spotify titles carry version suffixes that Soulseek users rarely include.
These helpers strip that noise and build fallback queries when the first
search returns nothing.
"""

import re

# Noise keywords that Spotify appends to track titles but Soulseek users never use.
# Named remixes (e.g. "Butch Vig Remix") are intentionally excluded — they
# represent distinct versions the user specifically selected.
_NOISE_PATTERN = (
    r"Mono|Stereo|Remaster(?:ed)?(?:\s+\d{4})?"
    r"|Deluxe(?:\s+Edition)?"
    r"|Ultimate\s+Mix|Single\s+Version|Album\s+Version"
    r"|Radio\s+Edit|Bonus\s+Track|Anniversary(?:\s+Edition)?"
    r"|Super\s+Deluxe|Special\s+Edition"
    r"|\d{4}\s+(?:Mix|Remix|Remaster(?:ed)?|Version)"
    r"|(?:German|French|Spanish|Italian|Japanese|Portuguese|English)\s+Version"
    r"|Remix"
)

# Matches trailing " - Remastered 2009", " - German Version 1989 Remix; ...", etc.
_VERSION_SUFFIX_RE = re.compile(
    r"\s*[-–]\s*(?:" + _NOISE_PATTERN + r").*$",
    re.IGNORECASE,
)

# Same patterns inside parentheses: "(Remastered 2009)", "(German Version)", etc.
_VERSION_PAREN_RE = re.compile(
    r"\s*\((?:" + _NOISE_PATTERN + r")[^)]*\)",
    re.IGNORECASE,
)

_QUOTE_CHARS = "'\"‘’“”"

_NOISE_WORDS = frozenset(
    {
        "single",
        "version",
        "long",
        "short",
        "full",
        "edit",
        "mix",
        "remastered",
        "remaster",
        "deluxe",
        "edition",
        "bonus",
        "track",
        "album",
        "mono",
        "stereo",
        "original",
        "extended",
        "feat",
        "featuring",
        "ft",
        "the",
        "an",
        "and",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "from",
        "by",
    }
)


def clean_search_title(title: str) -> str:
    """Strip Spotify version suffixes that add noise to Soulseek keyword search."""
    title = _VERSION_SUFFIX_RE.sub("", title)
    title = _VERSION_PAREN_RE.sub("", title)
    title = title.strip()
    if len(title) >= 2 and title[0] in _QUOTE_CHARS and title[-1] in _QUOTE_CHARS:
        title = title[1:-1].strip()
    return title


def build_reduced_queries(title: str, year: str) -> list[str]:
    """Build fallback search queries by dropping one word at a time and appending the year.

    Soulseek users sometimes block entire phrases (e.g. "Purple Rain").
    Removing one keyword at a time while adding the album year often
    bypasses server-side filters while still narrowing results enough
    to find the right track.
    """
    if not year:
        return []
    words = title.split()
    if len(words) < 2:
        return []
    queries: list[str] = []
    for i in range(len(words)):
        reduced = " ".join(words[:i] + words[i + 1 :])
        queries.append(f"{reduced} {year}")
    return queries


def has_non_latin_script(text: str) -> bool:
    """True when *text* contains characters from non-Latin scripts (CJK, Cyrillic, etc.)."""
    return any(c.isalpha() and ord(c) > 0x024F for c in text)


def extract_latin_keywords(title: str) -> list[str]:
    """Extract meaningful Latin keywords from a potentially mixed-script title.

    Strips common noise words so only distinctive keywords remain,
    e.g. ``["KURENAI"]`` from ``"紅 - KURENAI - シングル… - Single Long Version"``.
    """
    words = re.findall(r"[a-zA-Z]{2,}", title)
    return [w for w in words if w.lower() not in _NOISE_WORDS]


def parse_query_artist_title(query: str) -> tuple[str, str]:
    """Parse a free-text query into (artist, title) with title-casing.

    Tries " - " separator first. Otherwise assumes last word is title,
    rest is artist (e.g. "david bowie helden" → "David Bowie", "Helden").
    """
    if " - " in query:
        parts = query.split(" - ", 1)
        return parts[0].strip().title(), parts[1].strip().title()
    words = query.strip().split()
    if len(words) >= 3:
        return " ".join(words[:-1]).title(), words[-1].title()
    if len(words) == 2:
        return words[0].title(), words[1].title()
    return "", query.title()

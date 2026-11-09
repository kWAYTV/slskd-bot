"""Soulseek search-query construction.

Spotify titles carry version suffixes that Soulseek users rarely include.
These helpers strip that noise and build fallback queries when the first
search returns nothing.
"""

import re
import string

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


# Separators people type between artist and title: hyphen, en/em dash, pipe.
_SEPARATOR_RE = re.compile(r"\s+[-–—|]\s+")

# Bracketed noise pasted from video titles: "(Official Video)", "[HD]", "(Lyrics)".
_QUERY_NOISE_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(?:official|lyrics?|visuali[sz]er|audio|video|hd|hq|4k|1080p|720p)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_QUERY_NOISE_TAIL_RE = re.compile(
    r"\s+(?:official\s+(?:music\s+)?(?:video|audio)|lyric\s+video|lyrics|hd|hq|4k)\s*$",
    re.IGNORECASE,
)


def clean_query(query: str) -> str:
    """Strip pasted-title noise from a free-text query: brackets like (Official Video), outer quotes, extra spaces."""
    text = _QUERY_NOISE_RE.sub("", query)
    text = _QUERY_NOISE_TAIL_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text or query.strip()


def smart_case(text: str) -> str:
    """Capitalize words only when the text is all lowercase; keep "AC/DC", "McCartney", "DJ Shadow" as typed."""
    text = text.strip()
    if text and text == text.lower():
        return string.capwords(text)
    return text


def parse_query_artist_title(query: str) -> tuple[str, str]:
    """Parse a free-text query into (artist, title).

    An explicit separator wins: "artist - title", "artist – title", "artist | title".
    Otherwise the last word is the title and the rest the artist
    (e.g. "david bowie helden" → "David Bowie", "Helden"). Casing is only
    fixed for all-lowercase input.
    """
    query = clean_query(query)
    parts = _SEPARATOR_RE.split(query, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return smart_case(parts[0]), smart_case(parts[1])
    words = query.split()
    if len(words) >= 3:
        return smart_case(" ".join(words[:-1])), smart_case(words[-1])
    if len(words) == 2:
        return smart_case(words[0]), smart_case(words[1])
    return "", smart_case(query)

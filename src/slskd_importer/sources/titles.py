"""Title cleanup shared by the free-text sources: separators, numbering, unidentified rows, de-duplication."""

from __future__ import annotations

import re
from collections.abc import Iterable

from slskd_importer.sources.tracklist import Entry

MAX_ENTRIES = 500

# Same separators the query parser accepts between artist and title.
_SEPARATOR = r"\s[-–—|]\s"
_SEPARATOR_RE = re.compile(_SEPARATOR)

# Leading "01. ", "1) ", "#3. ", "[12:30] ", "(1:02:03) ", "[002] ", "[0??] ", "12:30 - ".
_NUMBERING_RE = re.compile(
    r"^\s*(?:"
    r"[\[(]\s*[\d?]{1,3}(?::\d{2}){0,2}\s*[\])]"
    r"|\d{1,2}(?::\d{2}){1,2}"
    r"|#?\d{1,3}[.)](?=\s)"
    r")\s*[-–—|:]?\s*"
)
# "01 - Artist - Title": a bare number is only numbering when a separator still follows it.
_BARE_NUMBER_RE = re.compile(rf"^\s*\d{{1,3}}{_SEPARATOR}\s*(?=.*{_SEPARATOR})")
_UNKNOWN_RE = re.compile(r"^(?:id|\?+|unknown|tba|n/?a)$", re.IGNORECASE)

# A trailing "[…]" is a label or catalogue tag ("[Drumcode]", "[ISH EP 04]") unless it names a version.
_TRAILING_TAG_RE = re.compile(r"\s*\[([^\]]+)\]\s*$")
_VERSION_WORD_RE = re.compile(
    r"\b(?:mix|remix|edit|version|dub|vip|bootleg|rework|flip|instrumental|acapella|original|extended|live|feat)\b",
    re.IGNORECASE,
)


def strip_label_tag(text: str) -> str:
    """Drop a trailing ``[Label]`` / ``[CAT 004]`` tag; ``[Extended Mix]`` and the like stay."""
    match = _TRAILING_TAG_RE.search(text)
    if match is None or _VERSION_WORD_RE.search(match.group(1)):
        return text
    return text[: match.start()].rstrip()


# What uploaders wrap around a track's name: "Premiere: …", "[FREE DL] …", "… (Out Now)", "… | Free Download".
_PROMO = (
    r"(?:(?:track|world|exclusive|sc|video|album)\s+)?premiere|exclusive|free\s+(?:download|dl)|out\s+now"
    r"|pre-?order|preview|first\s+listen|snippet|teaser|clip|full\s+(?:track|stream)|official\s+(?:audio|video)"
)
_PROMO_PREFIX_RE = re.compile(
    rf"^\s*(?:[\[(]\s*(?:{_PROMO})\s*[\])]\s*[:|–—-]?\s*|(?:{_PROMO})\s*[:|–—-]\s*)", re.IGNORECASE
)
_PROMO_SUFFIX_RE = re.compile(
    rf"\s*(?:[\[(]\s*(?:{_PROMO})\b[^\])]*[\])]|\s[|–—-]\s*(?:{_PROMO})\s*)\s*$", re.IGNORECASE
)


def strip_wrapping(text: str) -> str:
    """A track name without the promo words and label tags uploaders put around it.

    ``Premiere: A.Morgan — Decision [Newrhythmic Recs]`` gives ``A.Morgan — Decision``;
    a version tag such as ``[Extended Mix]`` stays.
    """
    previous = None
    while text != previous:
        previous = text
        text = _PROMO_PREFIX_RE.sub("", text, count=1)
        text = _PROMO_SUFFIX_RE.sub("", text, count=1)
        text = strip_label_tag(text).strip()
    return text


def split_once(text: str) -> tuple[str, str] | None:
    """``(left, right)`` around the first artist/title separator, or None when there is none."""
    parts = _SEPARATOR_RE.split(text, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 and all(parts) else None


def has_separator(text: str) -> bool:
    """True when *text* already reads like ``Artist - Title``."""
    return bool(_SEPARATOR_RE.search(text))


def strip_numbering(text: str) -> str:
    """Drop leading track numbers and timestamps from a tracklist row or chapter name."""
    previous = None
    while text != previous:
        previous = text
        text = _NUMBERING_RE.sub("", text, count=1)
        text = _BARE_NUMBER_RE.sub("", text, count=1)
    return text.strip()


def is_unidentified(text: str) -> bool:
    """True for rows a tracklist could not name, such as ``ID - ID`` or ``Artist - ID``."""
    parts = [part.strip() for part in _SEPARATOR_RE.split(text)]
    return any(not part or _UNKNOWN_RE.match(part) for part in parts)


def looks_like_track(text: str) -> bool:
    """True when *text* names an identified track (``Artist - Title``), not "Intro" or "ID - ID"."""
    return has_separator(text) and not is_unidentified(text)


def unique_entries(queries: Iterable[str]) -> list[Entry]:
    """Free-text entries in order, without blanks or exact duplicates, capped at ``MAX_ENTRIES``."""
    seen: dict[str, None] = {}
    for query in queries:
        query = query.strip()
        if query and query not in seen:
            seen[query] = None
            if len(seen) >= MAX_ENTRIES:
                break
    return [Entry(query=query) for query in seen]

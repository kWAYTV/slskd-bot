"""Whether a Soulseek copy is wanted, better, same recording, or keep-both name."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable

from slskd_importer.library.formats import LOSSY_EXTENSIONS
from slskd_importer.library.lossless import CHECKABLE_EXTENSIONS
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.sweep.audit import (
    CD_CUTOFF_KHZ,
    HIRES_CUTOFF_KHZ,
    TIER_CD,
    TIER_DAMAGED,
    TIER_HIRES,
    Audit,
)
from slskd_importer.sweep.fingerprint import SAME_RECORDING_SIMILARITY

logger = logging.getLogger(__name__)

MIN_GAIN_KHZ = 1.0
WANTED_MAX_DIFF_SECS = 3
# Same recording by length: within SAME_MAX_DIFF_SECS; up to REVIEW_MAX_DIFF_SECS the ear decides.
SAME_MAX_DIFF_SECS = 1.5
REVIEW_MAX_DIFF_SECS = 10.0
_STOP = {"the", "and", "feat", "ft", "featuring", "with", "vs", "x", "y", "de", "la", "el", "los", "las", "a", "of"}
_STOP |= {"dj", "mc"}
# Words that say a copy is not the artist's own recording.
NOT_ORIGINAL = (
    "karaoke",
    "tribute",
    "made famous",
    "in the style of",
    "as made famous",
    "cover version",
    "originally performed",
    "re recorded",
    "rerecorded",
    "re record",
    "our version",
    "taylor s version",
    "new version",
)
# Words that name another recording of the song, when the original's name and tags lack them.
OTHER_RECORDING = (
    "live",
    "unplugged",
    "acoustic",
    "remix",
    "remixes",
    "remixed",
    "session",
    "sessions",
    "demo",
    "orchestral",
    "symphonic",
    "mtv",
)
# Version words in a copy's title that the original's title lacks: the ear decides.
VERSION_WORDS = (
    "live",
    "remix",
    "edit",
    "version",
    "mix",
    "acoustic",
    "demo",
    "karaoke",
    "instrumental",
    "cover",
    "cast",
    "mono",
    "stereo",
)
# Words that may appear in a copy's tags without naming a new performer.
_NEUTRAL_EXTRA = {"version", "remaster", "remastered", "mono", "stereo", "single", "radio", "album", "original"}


def wanted(tier: str, copy: SearchResult, original_length: float) -> bool:
    """Whether a Soulseek copy could beat a song of *tier*, judged from the search result alone.

    Only lossless formats the spectrum check reads are worth a download (the
    rest could never be proven better), of about the original's length. A CD
    song only wants 24-bit copies above 48 kHz.
    """
    if copy.extension not in CHECKABLE_EXTENSIONS:
        return False
    if original_length and copy.length and abs(copy.length - original_length) > WANTED_MAX_DIFF_SECS:
        return False
    if tier == TIER_CD:
        return (copy.bit_depth or 0) >= 24 and (copy.sample_rate or 0) > 48000
    return tier != TIER_HIRES


def better(original: Audit, candidate: Audit) -> bool:
    """Whether a downloaded copy is a real improvement on the original, judged by its cutoff.

    It must decode cleanly and be lossless. A CD original needs genuine content
    above HIRES_CUTOFF_KHZ; a damaged one needs a copy no worse; a fake,
    uncertain or lossy one a cutoff of at least CD_CUTOFF_KHZ and MIN_GAIN_KHZ
    above its own.
    """
    if candidate.strict is not True or candidate.ext in LOSSY_EXTENSIONS or candidate.cutoff is None:
        return False
    c, oc = candidate.cutoff, original.cutoff or 0.0
    if original.tier == TIER_HIRES:
        return False
    if original.tier == TIER_CD:
        return (candidate.depth or 0) >= 24 and (candidate.rate or 0) > 48000 and c > HIRES_CUTOFF_KHZ
    if original.tier == TIER_DAMAGED:
        return c >= min(oc, CD_CUTOFF_KHZ) - 0.5
    return c >= max(CD_CUTOFF_KHZ, oc + MIN_GAIN_KHZ)


# ---------------------------------------------------------------------------
# Is it the same recording?
# ---------------------------------------------------------------------------


def norm(text: str) -> str:
    """Lowercase ASCII words: accents dropped, "&" as "and", everything else a space."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def base_title(title: str) -> str:
    """The title without brackets and without a " - Remastered"/" - Live" style suffix, normalised."""
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", title or "")
    title = re.sub(
        r"\s+-\s+(\d{4}\s+)?(remaster(ed)?|live|remix|radio edit|single version|album version|mono|stereo).*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return norm(title)


def _sig(text: str) -> set[str]:
    """The meaningful words of *text*: normalised, longer than one letter, stop words dropped."""
    return {w for w in norm(text).split() if len(w) > 1 and w not in _STOP}


def split_stem(stem: str) -> tuple[str, str]:
    """("Artist", "Title") of a library name "Artist - Title"; ("", stem) without the separator."""
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", stem.strip()


SAME = "same"
REVIEW = "review"
REJECT = "reject"


def sameness(original: Audit, candidate: Audit, stem: str) -> tuple[str, str]:
    """(SAME | REVIEW | REJECT, why) for a better copy, from its tags and length only.

    Rejected: another artist (no meaningful word shared), a karaoke, tribute or
    cover, a live/unplugged/acoustic/remix recording the original is not, a
    different title, or a length more than REVIEW_MAX_DIFF_SECS away. Same:
    within SAME_MAX_DIFF_SECS with no version word or performer the original
    lacks. Anything in between is for the ear. Remaster years and track
    numbers are not new performers.
    """
    artist, title = split_stem(stem)
    hard = _hard_reject(original, candidate, stem)
    if hard:
        return REJECT, hard
    diff = abs((candidate.length or 0) - (original.length or 0))
    extra, added = _extras(original, candidate, stem)
    if diff > REVIEW_MAX_DIFF_SECS:
        return REJECT, f"length differs {diff:.0f} s"
    if diff <= SAME_MAX_DIFF_SECS and not added and not extra:
        return SAME, f"length within {diff:.1f} s"
    return REVIEW, _review_why(diff, added, extra)


def _hard_reject(original: Audit, candidate: Audit, stem: str) -> str:
    """Why the copy cannot be this song at all, or "" when it may be."""
    artist, title = split_stem(stem)
    ct, ca, cal = candidate.title, candidate.artist, candidate.album
    orig_text = norm(" ".join([stem, original.artist, original.title, original.album]))
    if ca and artist and not (_sig(artist) & _sig(ca)):
        return f"artist tag '{ca}'"
    cand_text = norm(" ".join([ca, ct, cal]))
    if any(w in cand_text for w in NOT_ORIGINAL) and not any(w in orig_text for w in NOT_ORIGINAL):
        return f"not the original recording ('{ca} - {ct}', album '{cal}')"
    other = [w for w in OTHER_RECORDING if w in norm(ct + " " + cal).split() and w not in orig_text.split()]
    if other:
        return f"another recording: {', '.join(other)} in '{ct}' / '{cal}'"
    wanted_title = base_title(title)
    if ct and wanted_title and wanted_title not in norm(ct) and norm(ct) not in wanted_title:
        return f"title tag '{ct}'"
    return ""


def _extras(original: Audit, candidate: Audit, stem: str) -> tuple[list[str], list[str]]:
    """(names in the copy's artist/title tags the original lacks, version words its title adds)."""
    _, title = split_stem(stem)
    orig_text = " ".join([stem, original.artist, original.title, original.album])
    extra = _sig(candidate.artist + " " + candidate.title) - _sig(orig_text) - _NEUTRAL_EXTRA
    extra = sorted(w for w in extra if not w.isdigit())
    added = [w for w in VERSION_WORDS if w in norm(candidate.title).split() and w not in norm(title).split()]
    return extra, added


def _review_why(diff: float, added: list[str], extra: list[str]) -> str:
    why = f"length differs {diff:.1f} s"
    if added:
        why += f", title adds {', '.join(added)}"
    if extra:
        why += f", names not in your file: {', '.join(extra)}"
    return why


def judge(original: Audit, candidate: Audit, stem: str, similarity: float | None) -> tuple[str, str]:
    """(SAME | REVIEW | REJECT, why) for a better copy, with the fingerprint *similarity* when there is one.

    Without a fingerprint (None) this is sameness(). With one, the tags still
    reject a copy that cannot be this song; then the fingerprint decides:
    the same recording (SAME_RECORDING_SIMILARITY or more) is SAME when its
    length is within REVIEW_MAX_DIFF_SECS and its tags name nobody new, REVIEW
    otherwise; another recording is REVIEW, unless its length is off by more
    than REVIEW_MAX_DIFF_SECS. The sweep replaces nothing by itself: SAME and
    REVIEW both go to the owner's ear, SAME marked as the same recording.
    """
    if similarity is None:
        return sameness(original, candidate, stem)
    hard = _hard_reject(original, candidate, stem)
    if hard:
        return REJECT, hard
    diff = abs((candidate.length or 0) - (original.length or 0))
    extra, added = _extras(original, candidate, stem)
    if similarity >= SAME_RECORDING_SIMILARITY:
        if diff <= REVIEW_MAX_DIFF_SECS and not extra and not added:
            return SAME, f"same recording (fingerprint {similarity:.2f}), length within {diff:.1f} s"
        return REVIEW, f"same recording (fingerprint {similarity:.2f}), " + _review_why(diff, added, extra)
    if diff > REVIEW_MAX_DIFF_SECS:
        return REJECT, f"another recording (fingerprint {similarity:.2f}), length differs {diff:.0f} s"
    return REVIEW, f"another recording (fingerprint {similarity:.2f}), " + _review_why(diff, added, extra)


# ---------------------------------------------------------------------------
# Keep-both naming
# ---------------------------------------------------------------------------

_CONNECTOR_RE = re.compile(r"^(?:with|feat\.?|featuring|ft\.?)\s+", re.IGNORECASE)
_JOINER_RE = re.compile(r"^(?:[,&+/;:-]|and\b|x\b|vs\.?)\s*", re.IGNORECASE)
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SUFFIX_MAX = 80


def _clean_suffix(text: str) -> str:
    text = re.sub(r"\s+", " ", _FORBIDDEN.sub("", text)).strip(" .-")
    return text if len(text) <= _SUFFIX_MAX else text[:_SUFFIX_MAX].rsplit(" ", 1)[0].strip(" .-")


def keep_both_suffix(stem: str, original: Audit, candidate: Audit) -> str:
    """What sets the proposal apart, for its name: "with <performers>", a bracket of its title, or its album.

    From the artist tag when it holds the original artist plus someone else
    ("Elvis Presley with the Royal Philharmonic Orchestra" gives "with the
    Royal Philharmonic Orchestra"); else a bracket in its title the original's
    title lacks ("(1997 Version)"); else its album; else "alternate".
    """
    artist, title = split_stem(stem)
    ca = candidate.artist.strip()
    if ca and artist and norm(artist) in norm(ca) and norm(artist) != norm(ca):
        start = ca.casefold().find(artist.casefold())
        rest = (ca[:start] + ca[start + len(artist) :]).strip() if start >= 0 else ""
        rest = _JOINER_RE.sub("", rest).strip()
        if rest:
            rest = rest if _CONNECTOR_RE.match(rest) else f"with {rest}"
            return _clean_suffix(rest)
    for bracket in re.findall(r"[\(\[]([^\)\]]+)[\)\]]", candidate.title or ""):
        if norm(bracket) and norm(bracket) not in norm(title):
            return _clean_suffix(bracket)
    if candidate.album.strip() and norm(candidate.album) != norm(title):
        return _clean_suffix(candidate.album)
    return "alternate"


def keep_both_name(stem: str, ext: str, original: Audit, candidate: Audit, exists: Callable[[str], bool]) -> str:
    """The file name the proposal gets when both are kept: "Artist - Title (<suffix>).<ext>", never one taken."""
    suffix = keep_both_suffix(stem, original, candidate) or "alternate"
    name = f"{stem} ({suffix}).{ext}"
    n = 2
    while exists(name):
        name = f"{stem} ({suffix}) {n}.{ext}"
        n += 1
    return name

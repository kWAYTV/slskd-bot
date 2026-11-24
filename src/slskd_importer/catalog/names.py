"""Compare artist and title names written in different ways."""

from __future__ import annotations

import re
import unicodedata

# Words a catalog or a file name adds to a title without making it another version.
NEUTRAL_TITLE_WORDS = frozenset({"original", "mix", "version", "remaster", "remastered", "digital"})

# Letters Unicode does not decompose into a base letter plus an accent.
_LETTERS = str.maketrans(
    {"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L"}
)


def normalize(text: str) -> str:
    """Lowercase ASCII words: accents dropped, ``&`` as ``and``, punctuation as spaces."""
    # Apostrophes vanish in both spellings ("Ain't" / "Ain’t" / "Aint"), not turn into a space.
    text = re.sub(r"['’‘`´]", "", text).translate(_LETTERS)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text.replace("&", " and ")).strip()


def same_artist(wanted: str, found: str) -> bool:
    """Normalized names that are equal, or where one holds all of the other's words ("A", "A and B")."""
    if wanted == found:
        return True
    a, b = set(wanted.split()), set(found.split())
    return bool(a) and bool(b) and (a <= b or b <= a)


def same_title(wanted: str, found: str) -> bool:
    """Normalized titles that are equal, or differ only by neutral words ("Void" / "Void - Original Mix").

    A version word on one side only ("Extended", "Remix", "Live") makes them different.
    """
    if wanted == found:
        return True
    a, b = set(wanted.split()), set(found.split())
    return bool(a & b) and (a ^ b) <= NEUTRAL_TITLE_WORDS

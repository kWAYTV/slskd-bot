"""Audio formats accepted into the music library.

Single source of truth shared by local file placement (`library.files`)
and remote search filtering (`soulseek.parsing`).
"""

LOSSLESS_EXTENSIONS = frozenset({"flac", "alac", "wav", "aiff", "aif", "ape", "wv", "tta", "tak"})

# m4a counts as lossy: the extension alone cannot tell ALAC from AAC, and AAC
# is by far the common case on Soulseek.
LOSSY_EXTENSIONS = frozenset({"mp3", "aac", "m4a", "ogg", "opus", "wma"})

AUDIO_EXTENSIONS = LOSSLESS_EXTENSIONS | LOSSY_EXTENSIONS

AUDIO_SUFFIXES = {f".{extension}" for extension in AUDIO_EXTENSIONS}

# Search prefers these lossless formats before falling back to any audio.
# Order is the ranking: FLAC, then WAV, then AIFF, then ALAC.
PREFERRED_EXTENSIONS = frozenset({"flac", "wav", "aiff", "aif", "alac"})

_FORMAT_RANK = {
    "flac": 0,
    "wav": 1,
    "aiff": 2,
    "aif": 2,
    "alac": 3,
}


def is_lossless(extension: str) -> bool:
    """True when *extension* (with or without the dot, any case) is a lossless format."""
    return extension.lower().lstrip(".") in LOSSLESS_EXTENSIONS


def format_rank(extension: str) -> int:
    """Lower is better. Unknown / lossy extensions sort after preferred lossless."""
    return _FORMAT_RANK.get(extension.lower(), 4)

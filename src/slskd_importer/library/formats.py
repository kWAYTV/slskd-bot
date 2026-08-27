"""Audio formats accepted into the music library.

Single source of truth shared by local file placement (`library.files`)
and remote search filtering (`soulseek.parsing`).
"""

AUDIO_EXTENSIONS = {"flac", "alac", "wav", "aiff", "aif", "mp3", "aac", "m4a", "ogg", "opus", "wma"}

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


def format_rank(extension: str) -> int:
    """Lower is better. Unknown / lossy extensions sort after preferred lossless."""
    return _FORMAT_RANK.get(extension.lower(), 4)

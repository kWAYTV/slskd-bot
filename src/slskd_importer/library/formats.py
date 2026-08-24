"""Audio formats accepted into the music library.

Single source of truth shared by local file placement (`library.files`)
and remote search filtering (`soulseek.parsing`).
"""

AUDIO_EXTENSIONS = {"flac", "alac", "wav", "aiff", "mp3", "aac", "m4a", "ogg", "opus", "wma"}

AUDIO_SUFFIXES = {f".{extension}" for extension in AUDIO_EXTENSIONS}

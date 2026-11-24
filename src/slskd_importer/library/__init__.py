"""Music library: place files, write tags, embed artwork, analyze FLAC, build previews."""

from slskd_importer.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from slskd_importer.library.files import FileProcessor
from slskd_importer.library.lossless import LosslessVerdict, analyze_lossless
from slskd_importer.library.preview import convert_to_ogg, create_preview_clip

__all__ = [
    "FileProcessor",
    "LosslessVerdict",
    "analyze_lossless",
    "convert_to_ogg",
    "create_preview_clip",
    "embed_artwork_into_file",
    "fetch_spotify_artwork",
]

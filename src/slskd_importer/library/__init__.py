"""Music library: place files, embed artwork, analyze FLAC, build previews."""

from slskd_importer.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from slskd_importer.library.files import FileProcessor
from slskd_importer.library.flac import FlacVerdict, analyze_flac
from slskd_importer.library.preview import convert_to_ogg, create_preview_clip

__all__ = [
    "FileProcessor",
    "FlacVerdict",
    "analyze_flac",
    "convert_to_ogg",
    "create_preview_clip",
    "embed_artwork_into_file",
    "fetch_spotify_artwork",
]

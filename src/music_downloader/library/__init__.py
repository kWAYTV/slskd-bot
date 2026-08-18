"""Music library: place files, embed artwork, analyze FLAC, build previews."""

from music_downloader.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from music_downloader.library.files import FileProcessor
from music_downloader.library.flac import FlacVerdict, analyze_flac
from music_downloader.library.preview import convert_to_ogg, create_preview_clip

__all__ = [
    "FileProcessor",
    "FlacVerdict",
    "analyze_flac",
    "convert_to_ogg",
    "create_preview_clip",
    "embed_artwork_into_file",
    "fetch_spotify_artwork",
]

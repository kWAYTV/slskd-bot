"""Soulseek search, scoring, and download."""

from music_downloader.soulseek.client import SlskdClient
from music_downloader.soulseek.errors import SlskdUnavailableError
from music_downloader.soulseek.query import (
    build_reduced_queries,
    clean_search_title,
    extract_latin_keywords,
    has_non_latin_script,
    parse_query_artist_title,
)
from music_downloader.soulseek.result import DownloadStatus, SearchResult
from music_downloader.soulseek.scoring import ResultScorer

__all__ = [
    "DownloadStatus",
    "ResultScorer",
    "SearchResult",
    "SlskdClient",
    "SlskdUnavailableError",
    "build_reduced_queries",
    "clean_search_title",
    "extract_latin_keywords",
    "has_non_latin_script",
    "parse_query_artist_title",
]

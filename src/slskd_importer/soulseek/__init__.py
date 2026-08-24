"""Soulseek search, scoring, and download."""

from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.soulseek.query import (
    build_reduced_queries,
    clean_search_title,
    extract_latin_keywords,
    has_non_latin_script,
    parse_query_artist_title,
)
from slskd_importer.soulseek.result import DownloadStatus, SearchResult
from slskd_importer.soulseek.scoring import ResultScorer

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

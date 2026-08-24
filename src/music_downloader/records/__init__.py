"""Shared SQLite connection used by history and playlist import."""

from music_downloader.records.database import Database
from music_downloader.records.prefs import ChatPrefsRepository

__all__ = ["ChatPrefsRepository", "Database"]

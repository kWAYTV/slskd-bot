"""Shared SQLite connection used by history and playlist import."""

from slskd_importer.records.database import Database
from slskd_importer.records.prefs import ChatPrefsRepository

__all__ = ["ChatPrefsRepository", "Database"]

"""The library as the download queue uses it: owned check, placing a copy, undoing a save."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.history.store import HistoryRepository
from slskd_importer.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from slskd_importer.library.files import FileProcessor
from slskd_importer.soulseek.result import SearchResult

logger = logging.getLogger(__name__)


@dataclass
class Placed:
    name: str
    history_id: int


class LibraryShelf:
    """The library as the queue sees it: is a track there, put one in, take one out."""

    def __init__(self, processor: FileProcessor, spotify: SpotifyResolver, history: HistoryRepository) -> None:
        self._processor = processor
        self._spotify = spotify
        self._history = history

    def owned_as(self, track: TrackInfo) -> str | None:
        """The library file name holding *track*, or None. Blocking.

        A past save counts only while its file is still there, so a song
        deleted by hand can be fetched again.
        """
        exact = self._processor.find_exact(track.artist, track.title)
        if exact:
            return exact[0]
        saved = self._history.find_success(track.artist, track.title, track.spotify_url)
        if saved and os.path.isfile(os.path.join(self._processor.output_dir, saved.filename)):
            return saved.filename
        return None

    async def place(self, track: TrackInfo, result: SearchResult, path: str, chat_id: int) -> Placed | None:
        """Rename *path* into the library with canonical tags and artwork; record it. None when placing failed."""
        target = await asyncio.to_thread(
            self._processor.process_file, path, track.artist, track.title, album=track.album, year=track.year
        )
        if not target:
            return None
        await asyncio.to_thread(self._embed_artwork, target, track)
        name = os.path.basename(target)
        history_id = await asyncio.to_thread(self.record, track, result, "success", chat_id, name)
        return Placed(name, history_id)

    def record(self, track: TrackInfo, result: SearchResult, status: str, chat_id: int, name: str = "") -> int:
        """Add a history row for an outcome. Blocking."""
        return self._history.add(
            artist=track.artist,
            title=track.title,
            album=track.album,
            filename=name or f"{track.filename}.{result.extension}",
            source_user=result.username,
            remote_path=result.filename,
            status=status,
            duration_secs=track.duration_secs,
            file_size=result.size,
            chat_id=chat_id,
            spotify_url=track.spotify_url,
        )

    def remove(self, name: str, history_id: int | None) -> bool:
        """Delete a saved file from the library and mark its history row undone. Blocking."""
        if not self._processor.delete_library_file(name):
            return False
        if history_id is not None:
            self._history.set_status(history_id, "undone")
        return True

    def path_of(self, name: str) -> str:
        return os.path.join(self._processor.output_dir, name)

    def _embed_artwork(self, target: str, track: TrackInfo) -> None:
        art = fetch_spotify_artwork(self._spotify.sp, track.artist, track.title)
        if art and embed_artwork_into_file(target, art):
            logger.info("Embedded artwork into %s", target)

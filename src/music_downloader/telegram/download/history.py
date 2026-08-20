"""Record download outcomes in the history store."""

from __future__ import annotations

import asyncio

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult


async def add_history(self, track: TrackInfo, result: SearchResult, status: str, chat_id: int | None = None):
    await asyncio.to_thread(
        self.history_repo.add,
        artist=track.artist,
        title=track.title,
        album=track.album,
        filename=f"{track.artist} - {track.title}.{result.extension}",
        source_user=result.username,
        remote_path=result.filename,
        status=status,
        duration_secs=track.duration_secs,
        file_size=result.size,
        chat_id=chat_id,
        spotify_url=track.spotify_url,
    )

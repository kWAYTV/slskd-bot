"""Resolve a library stem to a TrackInfo: Spotify first, MusicBrainz second."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from slskd_importer.catalog.musicbrainz import MusicBrainzClient
from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.catalog.track import TrackInfo

logger = logging.getLogger(__name__)

# Duration within this many seconds of the library file counts as confident.
_DURATION_TOLERANCE_SECS = 5.0
MUSICBRAINZ_MAX = 10


@dataclass(frozen=True)
class ResolveCandidate:
    track: TrackInfo
    confident: bool


def _duration_ok(track: TrackInfo, length_secs: float | None) -> bool:
    if length_secs is None or length_secs <= 0 or track.duration_ms <= 0:
        return True
    return abs(track.duration_secs - length_secs) <= _DURATION_TOLERANCE_SECS


def _closest_first(tracks: list[TrackInfo], length_secs: float | None) -> list[TrackInfo]:
    if length_secs is None or length_secs <= 0:
        return tracks
    return sorted(tracks, key=lambda t: abs(t.duration_secs - length_secs) if t.duration_ms else 10**9)


async def resolve_match(
    spotify: SpotifyResolver,
    musicbrainz: MusicBrainzClient,
    artist: str,
    title: str,
    length_secs: float | None,
) -> list[ResolveCandidate]:
    """Candidates for Artist/Title, Spotify then MusicBrainz. First confident wins for the sweep."""
    import asyncio

    query = f"{artist} {title}".strip()
    tracks = await asyncio.to_thread(spotify.search_multiple, query, 10)
    out: list[ResolveCandidate] = []
    for track in tracks:
        out.append(ResolveCandidate(track, confident=_duration_ok(track, length_secs)))
    if any(c.confident for c in out):
        return out

    mb = await asyncio.to_thread(musicbrainz.search_recordings, artist, title)
    mb = _closest_first(mb, length_secs)[:MUSICBRAINZ_MAX]
    for track in mb:
        out.append(ResolveCandidate(track, confident=_duration_ok(track, length_secs)))
    if not out:
        logger.info("No Spotify/MusicBrainz match for %r - %r", artist, title)
    return out

"""Whether a Soulseek copy is the requested song at all: its path must name it.

The search falls back to looser queries (title only, fewer keywords) when the
full one finds nothing, so a ranked copy may be another artist's song with the
same title. Only copies whose remote path carries every word of the title and
at least one word of the artist count as found; the rest are dropped.
"""

from __future__ import annotations

from slskd_importer.catalog.names import normalize
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult


def names_the_song(track: TrackInfo, copy: SearchResult) -> bool:
    path_words = set(normalize(copy.filename).split())
    title_words = normalize(track.title).split()
    artist_words = normalize(track.artist).split()
    if not title_words or not all(word in path_words for word in title_words):
        return False
    return not artist_words or any(word in path_words for word in artist_words)


def sure_copies(track: TrackInfo, ranked: list[SearchResult]) -> list[SearchResult]:
    """The ranked copies that name the song, best first."""
    return [copy for copy in ranked if names_the_song(track, copy)]

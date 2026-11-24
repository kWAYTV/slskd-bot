"""Find the catalog track a free-text query means.

``Artist - Title`` queries use Spotify field filters first; anything else is
free text. Candidates are deduplicated, filtered by artist, and editions of the
same recording are collapsed, so the first candidate is the best guess.
"""

from __future__ import annotations

from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.query import clean_query, parse_query_artist_title

FETCH_LIMIT = 50
# Editions of the same recording (album, compilation, reissue) differ by this much at most.
SAME_EDITION_SECS = 2
_SEPARATORS = (" - ", " – ", " — ", " | ")


def has_separator(query: str) -> bool:
    return any(sep in query for sep in _SEPARATORS)


def find_candidates(spotify: SpotifyResolver, query: str) -> list[TrackInfo]:
    """Catalog candidates for *query*, best first. Blocking."""
    cleaned = clean_query(query)
    artist, title = parse_query_artist_title(query)
    tracks: list[TrackInfo] = []
    if artist and title and has_separator(cleaned):
        tracks = spotify.search_fielded(artist, title, FETCH_LIMIT)
    if not tracks:
        tracks = spotify.search_multiple(cleaned, FETCH_LIMIT)
    return filter_candidates(query, tracks)


def identify(spotify: SpotifyResolver, query: str) -> TrackInfo:
    """The track *query* most likely means; a duration-free track parsed from the text when the catalog has none."""
    candidates = find_candidates(spotify, query)
    return candidates[0] if candidates else track_from_text(query)


def track_from_text(query: str) -> TrackInfo:
    """A track built from the query alone: no album, no length (duration scoring is then flat)."""
    artist, title = parse_query_artist_title(query)
    return TrackInfo(artist=artist, title=title, album="", duration_ms=0, spotify_url="", year="")


def collapse_editions(tracks: list[TrackInfo]) -> list[TrackInfo]:
    """Keep one entry per artist+title+length, preferring the earliest release."""
    kept: list[TrackInfo] = []
    for track in tracks:
        key = (track.artist.lower(), track.title.lower())
        twin = next(
            (
                k
                for k in kept
                if (k.artist.lower(), k.title.lower()) == key
                and abs(k.duration_secs - track.duration_secs) <= SAME_EDITION_SECS
            ),
            None,
        )
        if twin is None:
            kept.append(track)
        elif track.year and (not twin.year or track.year < twin.year):
            kept[kept.index(twin)] = track
    return kept


def _dedup(tracks: list[TrackInfo]) -> list[TrackInfo]:
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for track in tracks:
        key = (track.artist.lower(), track.title.lower(), track.album.lower())
        if key not in seen:
            seen.add(key)
            unique.append(track)
    return unique


def filter_candidates(query: str, tracks: list[TrackInfo]) -> list[TrackInfo]:
    """Dedup, prefer candidates whose artist the query names, collapse editions."""
    query = clean_query(query)
    query_lower = query.lower()
    query_words = set(query_lower.split())
    query_artist = parse_query_artist_title(query)[0].lower() if has_separator(query) else ""

    unique = _dedup(tracks)
    named, others = [], []
    for track in unique:
        artist = track.artist.lower()
        if query_artist and query_artist not in artist:
            continue
        artist_words = set(artist.split())
        if (len(artist_words) >= 2 and artist in query_lower) or artist_words.issubset(query_words):
            named.append(track)
        else:
            others.append(track)

    named.sort(key=lambda t: len(t.artist), reverse=True)
    # When the artist filter empties the list, fall back to plain dedup.
    return collapse_editions(named + others or unique)

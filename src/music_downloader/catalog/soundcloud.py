"""SoundCloud track identity: model, title normalization, Spotify matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TITLE_SEPARATORS = ("-", "–", "—", ":", "|")


@dataclass
class SoundCloudTrack:
    """Artist/title as advertised by SoundCloud."""

    artist: str
    title: str

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


def strip_artist_prefix(artist: str, title: str) -> str:
    """Drop a leading 'Artist - ' from the title (SoundCloud titles often embed the artist)."""
    if not artist or len(title) <= len(artist):
        return title
    if not title.casefold().startswith(artist.casefold()):
        return title
    rest = title[len(artist) :].lstrip()
    if rest and rest[0] in _TITLE_SEPARATORS:
        rest = rest[1:].strip()
        if rest:
            return rest
    return title


def _normalize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def matches_spotify_candidate(sc_track: SoundCloudTrack, candidate_artist: str, candidate_title: str) -> bool:
    """True when a Spotify candidate plausibly is the same song as the SoundCloud track.

    Guards against the fuzzy Spotify search silently substituting a different
    track by the same artist when the SoundCloud song isn't on Spotify.
    """
    sc_words = _normalize(sc_track.title)
    cand_words = _normalize(candidate_title)
    if not sc_words or not cand_words:
        return False
    overlap = len(sc_words & cand_words) / min(len(sc_words), len(cand_words))
    if overlap < 0.5:
        return False

    if sc_track.artist:
        sc_artist = _normalize(sc_track.artist)
        cand_artist = _normalize(candidate_artist)
        if not (sc_artist & cand_artist):
            return False
    return True

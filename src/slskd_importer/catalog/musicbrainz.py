"""MusicBrainz recording search: fallback when Spotify has no confident match."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable

import httpx

from slskd_importer import __version__
from slskd_importer.catalog.track import TrackInfo

logger = logging.getLogger(__name__)

API_URL = "https://musicbrainz.org/ws/2/recording"
USER_AGENT = f"telegram-slskd-local-bot/{__version__} ( https://github.com/GeiserX/telegram-slskd-local-bot )"
MIN_INTERVAL_SECS = 1.0
TIMEOUT_SECS = 10.0
RETRY_503_SECS = 2.0

_OTHER_RECORDING_RE = re.compile(
    r"\b(live|demo|remix|remixed|acoustic|instrumental|karaoke|cover|rehearsal|unplugged|dj[\s-]?mix|megamix)\b",
    re.IGNORECASE,
)
_LUCENE_SPECIAL_RE = re.compile(r'([\\"])')


def _phrase(text: str) -> str:
    return '"' + _LUCENE_SPECIAL_RE.sub(r"\\\1", text.strip()) + '"'


def _artist_credit(recording: dict) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in recording.get("artist-credit", [])).strip()


def recording_to_track(recording: dict) -> TrackInfo:
    releases = recording.get("releases") or [{}]
    year = (recording.get("first-release-date") or releases[0].get("date") or "")[:4]
    return TrackInfo(
        artist=_artist_credit(recording),
        title=recording.get("title", ""),
        album=releases[0].get("title", ""),
        duration_ms=int(recording.get("length") or 0),
        spotify_url="",
        year=year,
    )


class MusicBrainzClient:
    """Searches MusicBrainz recordings, one request per second at most."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._http = http or httpx.Client(timeout=TIMEOUT_SECS)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: float | None = None

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            wait = self._last_request + MIN_INTERVAL_SECS - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def search_recordings(self, artist: str, title: str, limit: int = 25) -> list[TrackInfo]:
        if not title.strip():
            return []
        query = f"recording:{_phrase(title)}"
        if artist.strip():
            query = f"artist:{_phrase(artist)} AND {query}"
        params = {"query": query, "fmt": "json", "limit": str(limit)}
        with self._lock:
            self._wait_turn()
            try:
                response = self._http.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
                if response.status_code == 503:
                    self._sleep(RETRY_503_SECS)
                    self._last_request = self._clock()
                    response = self._http.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                recordings = response.json().get("recordings", [])
            except (httpx.HTTPError, ValueError):
                logger.exception("MusicBrainz search failed for %r - %r", artist, title)
                return []
        title_says_other = bool(_OTHER_RECORDING_RE.search(title))
        tracks = []
        for rec in recordings:
            if not rec.get("id") or not rec.get("title"):
                continue
            if not title_says_other and _OTHER_RECORDING_RE.search(rec.get("disambiguation") or ""):
                continue
            tracks.append(recording_to_track(rec))
        return tracks

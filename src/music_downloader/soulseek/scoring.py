"""Rank Soulseek results against a catalog track.

Scoring (100 points):
  duration match (40) + audio quality (25) + source reliability (20) + filename (15)
"""

import logging
import re

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.parsing import parse_search_responses
from music_downloader.soulseek.result import SearchResult

logger = logging.getLogger(__name__)

DURATION_MAX_POINTS = 40.0
DURATION_CLOSE_POINTS = 25.0
DURATION_FLAT_POINTS = 15.0
QUALITY_HIRES_POINTS = 15.0
QUALITY_CD_POINTS = 10.0
SAMPLE_RATE_HIRES_POINTS = 10.0
SAMPLE_RATE_CD_POINTS = 5.0
SLOT_AVAILABLE_POINTS = 7.5
SPEED_MAX_POINTS = 7.5
QUEUE_MAX_POINTS = 5.0
FILENAME_PART_POINTS = 7.5

QUALITY_PREFER_HIRES = "hires"
QUALITY_PREFER_CD = "cd"


class ResultScorer:
    """Scores and ranks slskd search results against a catalog track."""

    def __init__(
        self,
        duration_tolerance_secs: int = 5,
        exclude_keywords: list[str] | None = None,
    ):
        self.duration_tolerance = duration_tolerance_secs
        self.exclude_keywords = exclude_keywords or [
            "live",
            "remix",
            "acoustic",
            "karaoke",
            "instrumental",
            "cover",
            "demo",
            "radio edit",
            "tribute",
        ]

    def score_results(
        self,
        results: list[SearchResult],
        track: TrackInfo,
        max_duration_diff: int | None = None,
        quality_preference: str = QUALITY_PREFER_HIRES,
    ) -> list[SearchResult]:
        """
        Score and rank search results against the reference track.
        Filters out unwanted results and sorts by score (highest first).
        """
        scored = []
        for result in results:
            score = self._calculate_score(result, track, max_duration_diff, quality_preference)
            if score is None:
                continue
            result.score = score
            scored.append(result)

        scored.sort(key=lambda r: r.score, reverse=True)
        deduplicated = _dedup_by_basename(scored)

        logger.info(f"Scored {len(scored)} results, {len(deduplicated)} after dedup (from {len(results)} total)")
        return deduplicated

    def _calculate_score(
        self,
        result: SearchResult,
        track: TrackInfo,
        max_duration_diff: int | None = None,
        quality_preference: str = QUALITY_PREFER_HIRES,
    ) -> float | None:
        """Calculate a score for a single result, or None to exclude it."""
        excluded = self._excluded_keyword(result, track)
        if excluded:
            logger.debug(f"Excluded (keyword '{excluded}'): {result.basename}")
            return None

        duration = self._duration_points(result, track, max_duration_diff)
        if duration is None:
            logger.debug(f"Excluded (duration {result.length}s vs {track.duration_secs}s): {result.basename}")
            return None

        score = (
            duration
            + _quality_points(result, quality_preference)
            + _source_points(result)
            + _filename_points(result, track)
        )
        return round(score, 2)

    def _excluded_keyword(self, result: SearchResult, track: TrackInfo) -> str | None:
        """Return the exclude keyword that disqualifies this result, if any."""
        basename_lower = result.basename.lower()
        title_lower = track.title.lower()
        for keyword in self.exclude_keywords:
            if keyword in basename_lower and keyword.lower() not in title_lower:
                return keyword
        return None

    def _duration_points(
        self,
        result: SearchResult,
        track: TrackInfo,
        max_duration_diff: int | None,
    ) -> float | None:
        """Duration points (40 max), or None to exclude the result."""
        target_secs = track.duration_secs
        if target_secs == 0:
            return DURATION_FLAT_POINTS
        if result.length is None or result.length <= 0:
            return DURATION_FLAT_POINTS

        diff = abs(result.length - target_secs)
        if diff <= self.duration_tolerance:
            return DURATION_MAX_POINTS - (diff * 2)
        if diff <= 10:
            return DURATION_CLOSE_POINTS - (diff - self.duration_tolerance) * 3
        if diff <= 30:
            return max(0.0, 10.0 - (diff - 10) * 0.5)
        if max_duration_diff is not None and diff <= max_duration_diff:
            return 0.0
        return None


def _dedup_by_basename(results: list[SearchResult]) -> list[SearchResult]:
    """Keep the first (highest-scored) result per lowercased basename."""
    seen: set[str] = set()
    deduplicated = []
    for result in results:
        key = result.basename.lower()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(result)
    return deduplicated


def _quality_points(result: SearchResult, preference: str) -> float:
    """Audio-quality points (25 max). ``cd`` preference favors 16/44.1 over hi-res."""
    prefer_cd = preference == QUALITY_PREFER_CD
    return _bit_depth_points(result.bit_depth, prefer_cd) + _sample_rate_points(result.sample_rate, prefer_cd)


def _bit_depth_points(bit_depth: int | None, prefer_cd: bool) -> float:
    if not bit_depth:
        return 0.0
    if bit_depth >= 24:
        return QUALITY_CD_POINTS if prefer_cd else QUALITY_HIRES_POINTS
    if bit_depth == 16:
        return QUALITY_HIRES_POINTS if prefer_cd else QUALITY_CD_POINTS
    return SAMPLE_RATE_CD_POINTS


def _sample_rate_points(sample_rate: int | None, prefer_cd: bool) -> float:
    if not sample_rate:
        return 0.0
    if sample_rate >= 88200:
        return SAMPLE_RATE_CD_POINTS if prefer_cd else SAMPLE_RATE_HIRES_POINTS
    if sample_rate == 48000:
        return 7.0
    if sample_rate == 44100:
        return SAMPLE_RATE_HIRES_POINTS if prefer_cd else 6.0
    return 3.0


def _source_points(result: SearchResult) -> float:
    """Source reliability points (20 max): free slots, upload speed, queue length."""
    points = 0.0
    if result.has_free_slot:
        points += SLOT_AVAILABLE_POINTS
    if result.upload_speed > 0:
        points += min(result.upload_speed / 1_000_000, 10) * (SPEED_MAX_POINTS / 10)
    if result.queue_length == 0:
        points += QUEUE_MAX_POINTS
    elif result.queue_length < 5:
        points += 2.0
    return points


def _filename_points(result: SearchResult, track: TrackInfo) -> float:
    """Filename relevance points (15 max): artist/title word overlap."""
    filename_words = set(re.findall(r"\w+", result.filename.lower()))
    artist_words = set(re.findall(r"\w+", track.artist.lower()))
    title_words = set(re.findall(r"\w+", track.title.lower()))

    artist_match = len(artist_words & filename_words) / max(len(artist_words), 1)
    title_match = len(title_words & filename_words) / max(len(title_words), 1)
    return (artist_match + title_match) * FILENAME_PART_POINTS


def rank_responses(
    raw_responses: list[dict],
    track: TrackInfo,
    scorer: ResultScorer,
    max_duration_diff: int | None = None,
    quality_preference: str | None = None,
) -> tuple[list[SearchResult], bool]:
    """Parse and score responses: FLAC first, any audio as fallback.

    Returns (ranked results, used-non-FLAC-fallback).
    """
    score_kwargs = {"max_duration_diff": max_duration_diff} if max_duration_diff else {}
    if quality_preference:
        score_kwargs["quality_preference"] = quality_preference
    flac_results = parse_search_responses(raw_responses, flac_only=True)
    ranked = scorer.score_results(flac_results, track, **score_kwargs)
    if ranked:
        return ranked, False
    all_audio = parse_search_responses(raw_responses, flac_only=False)
    ranked = scorer.score_results(all_audio, track, **score_kwargs)
    return ranked, bool(ranked)

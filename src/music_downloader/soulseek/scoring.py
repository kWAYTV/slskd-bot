"""Rank Soulseek results against a catalog track.

Scoring (100 points):
  duration match (40) + audio quality (25) + source reliability (20) + filename (15)
"""

import logging
import re

from music_downloader.catalog.track import TrackInfo
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
            if score is not None:
                result.score = score
                scored.append(result)

        scored.sort(key=lambda r: r.score, reverse=True)

        seen_basenames = set()
        deduplicated = []
        for result in scored:
            basename_key = result.basename.lower()
            if basename_key not in seen_basenames:
                seen_basenames.add(basename_key)
                deduplicated.append(result)

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
        score = 0.0

        filename_lower = result.filename.lower()
        basename_lower = result.basename.lower()

        for keyword in self.exclude_keywords:
            if keyword in basename_lower:
                if keyword.lower() not in track.title.lower():
                    logger.debug(f"Excluded (keyword '{keyword}'): {result.basename}")
                    return None

        target_secs = track.duration_secs
        if target_secs == 0:
            score += DURATION_FLAT_POINTS
        elif result.length is not None and result.length > 0:
            diff = abs(result.length - target_secs)

            if diff <= self.duration_tolerance:
                score += DURATION_MAX_POINTS - (diff * 2)
            elif diff <= 10:
                score += DURATION_CLOSE_POINTS - (diff - self.duration_tolerance) * 3
            elif diff <= 30:
                score += max(0.0, 10.0 - (diff - 10) * 0.5)
            elif max_duration_diff is not None and diff <= max_duration_diff:
                pass
            else:
                logger.debug(f"Excluded (duration {result.length}s vs {target_secs}s): {result.basename}")
                return None
        else:
            score += DURATION_FLAT_POINTS

        score += _quality_points(result, quality_preference)

        if result.has_free_slot:
            score += SLOT_AVAILABLE_POINTS

        if result.upload_speed > 0:
            speed_score = min(result.upload_speed / 1_000_000, 10) * (SPEED_MAX_POINTS / 10)
            score += speed_score

        if result.queue_length == 0:
            score += QUEUE_MAX_POINTS
        elif result.queue_length < 5:
            score += 2.0

        artist_lower = track.artist.lower()
        title_lower = track.title.lower()

        artist_words = set(re.findall(r"\w+", artist_lower))
        title_words = set(re.findall(r"\w+", title_lower))
        filename_words = set(re.findall(r"\w+", filename_lower))

        artist_match = len(artist_words & filename_words) / max(len(artist_words), 1)
        title_match = len(title_words & filename_words) / max(len(title_words), 1)

        score += artist_match * SPEED_MAX_POINTS
        score += title_match * SPEED_MAX_POINTS

        return round(score, 2)


def _quality_points(result: SearchResult, preference: str) -> float:
    """Audio-quality points (25 max). ``cd`` preference favors 16/44.1 over hi-res."""
    prefer_cd = preference == QUALITY_PREFER_CD
    points = 0.0

    if result.bit_depth:
        if result.bit_depth >= 24:
            points += QUALITY_CD_POINTS if prefer_cd else QUALITY_HIRES_POINTS
        elif result.bit_depth == 16:
            points += QUALITY_HIRES_POINTS if prefer_cd else QUALITY_CD_POINTS
        else:
            points += SAMPLE_RATE_CD_POINTS

    if result.sample_rate:
        if result.sample_rate >= 88200:
            points += SAMPLE_RATE_CD_POINTS if prefer_cd else SAMPLE_RATE_HIRES_POINTS
        elif result.sample_rate == 48000:
            points += 7.0
        elif result.sample_rate == 44100:
            points += SAMPLE_RATE_HIRES_POINTS if prefer_cd else 6.0
        else:
            points += 3.0

    return points

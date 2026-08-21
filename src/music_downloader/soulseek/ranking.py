"""Rank raw slskd responses: prefer FLAC, fall back to any audio format."""

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.parsing import parse_search_responses
from music_downloader.soulseek.result import SearchResult
from music_downloader.soulseek.scoring import ResultScorer


def rank_responses(
    raw_responses: list[dict],
    track: TrackInfo,
    scorer: ResultScorer,
    max_duration_diff: int | None = None,
    quality_preference: str | None = None,
) -> tuple[list[SearchResult], bool]:
    """Parse and score responses. Returns (ranked results, used-non-FLAC-fallback)."""
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

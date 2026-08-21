"""Scorer branch coverage: duration tiers, quality edge cases, queue penalty."""

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult
from music_downloader.soulseek.scoring import ResultScorer


def _make_track(duration_ms: int = 162000) -> TrackInfo:
    return TrackInfo(
        artist="Nancy Sinatra",
        title="Bang Bang",
        album="Album",
        duration_ms=duration_ms,
        spotify_url="",
        year="1966",
    )


def _make_result(
    filename: str = "Nancy Sinatra - Bang Bang.flac",
    length: int | None = 162,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    has_free_slot: bool = False,
    upload_speed: int = 0,
    queue_length: int = 0,
) -> SearchResult:
    return SearchResult(
        username="user1",
        filename=f"\\Music\\{filename}",
        size=30_000_000,
        bit_depth=bit_depth,
        sample_rate=sample_rate,
        length=length,
        has_free_slot=has_free_slot,
        upload_speed=upload_speed,
        queue_length=queue_length,
    )


class TestScorerDurationBranches:
    """Cover duration scoring branches."""

    def test_duration_diff_6_to_10(self):
        """Duration diff between tolerance (5) and 10s."""
        scorer = ResultScorer(duration_tolerance_secs=5)
        track = _make_track(duration_ms=162000)  # 162s
        # diff = 8s (between 5 and 10)
        result = _make_result(length=170)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1
        assert scored[0].score > 0

    def test_duration_diff_11_to_30(self):
        """Duration diff between 10 and 30s."""
        scorer = ResultScorer(duration_tolerance_secs=5)
        track = _make_track(duration_ms=162000)  # 162s
        # diff = 20s (between 10 and 30)
        result = _make_result(length=182)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1
        assert scored[0].score > 0

    def test_duration_diff_beyond_30_with_max_override(self):
        """Duration diff > 30s but within max_duration_diff passes."""
        scorer = ResultScorer(duration_tolerance_secs=5)
        track = _make_track(duration_ms=162000)  # 162s
        # diff = 40s (> 30 but within max_duration_diff=60)
        result = _make_result(length=202)
        scored = scorer.score_results([result], track, max_duration_diff=60)
        assert len(scored) == 1
        # Gets 0 duration points but is not excluded
        assert scored[0].score >= 0


class TestScorerQualityBranches:
    """Cover audio quality edge cases."""

    def test_bit_depth_below_16(self):
        scorer = ResultScorer()
        track = _make_track()
        result = _make_result(bit_depth=8, sample_rate=44100)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1

    def test_sample_rate_48000(self):
        scorer = ResultScorer()
        track = _make_track()
        result = _make_result(bit_depth=16, sample_rate=48000)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1

    def test_sample_rate_below_44100(self):
        scorer = ResultScorer()
        track = _make_track()
        result = _make_result(bit_depth=16, sample_rate=22050)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1


class TestScorerQueueBranch:
    """Cover the queue_length penalty branch."""

    def test_queue_length_between_1_and_4(self):
        scorer = ResultScorer()
        track = _make_track()
        result = _make_result(queue_length=3)
        scored = scorer.score_results([result], track)
        assert len(scored) == 1
        # Compare with queue_length=0 to confirm lower score
        result_empty_q = _make_result(queue_length=0, filename="Nancy Sinatra - Bang Bang v2.flac")
        scored_both = scorer.score_results([result, result_empty_q], track)
        empty_q_score = next(r for r in scored_both if "v2" in r.filename).score
        short_q_score = next(r for r in scored_both if "v2" not in r.filename).score
        assert empty_q_score > short_q_score

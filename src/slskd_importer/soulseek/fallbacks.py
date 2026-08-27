"""Four-tier Soulseek search policy with progressively looser queries.

Tiers: full ``artist title`` query, title-only, keyword reduction + year,
artist + Latin keywords.  Each tier stops early when the caller reports
cancellation via ``is_cancelled``.
"""

import logging
from collections.abc import Awaitable, Callable

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.query import (
    build_reduced_queries,
    clean_search_title,
    extract_latin_keywords,
    has_non_latin_script,
)
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.soulseek.scoring import ResultScorer, rank_responses

logger = logging.getLogger(__name__)

OnTier = Callable[[str], Awaitable[None]]


async def search_with_fallbacks(
    client: SlskdClient,
    scorer: ResultScorer,
    track: TrackInfo,
    *,
    timeout_secs: int,
    is_cancelled: Callable[[], bool],
    on_tier: OnTier | None = None,
) -> tuple[list[SearchResult], bool, bool]:
    """Run the tiered search. Returns (ranked, used-lossy-fallback, cancelled)."""
    clean_title = clean_search_title(track.title)
    search_query = f"{track.artist} {clean_title}"

    raw_responses = await client.search(search_query, timeout_secs=timeout_secs)
    if is_cancelled():
        return [], False, True
    ranked, is_fallback = rank_responses(raw_responses, track, scorer)
    if ranked:
        return ranked, is_fallback, False

    if on_tier:
        await on_tier("title-only")
    logger.info("No results for '%s', retrying with title-only: '%s'", search_query, clean_title)
    raw_responses = await client.search(clean_title, timeout_secs=timeout_secs)
    if is_cancelled():
        return [], False, True
    ranked, is_fallback = rank_responses(raw_responses, track, scorer)
    if ranked:
        return ranked, is_fallback, False

    if not has_non_latin_script(clean_title):
        reduced_queries = build_reduced_queries(clean_title, track.year)
        if reduced_queries:
            if on_tier:
                await on_tier("keywords")
            logger.info("No results for title-only '%s', trying keyword reduction + year", clean_title)
            for fallback_query in reduced_queries:
                if is_cancelled():
                    return [], False, True
                raw_responses = await client.search(fallback_query, timeout_secs=timeout_secs)
                ranked, is_fallback = rank_responses(raw_responses, track, scorer)
                if ranked:
                    logger.info("Keyword-reduction fallback hit: '%s'", fallback_query)
                    return ranked, is_fallback, False

    latin_kw = extract_latin_keywords(clean_title)
    fb4_query = f"{track.artist} {' '.join(latin_kw)}" if latin_kw else track.artist
    if on_tier:
        await on_tier("artist-keywords")
    logger.info("Trying artist + Latin keywords fallback: '%s'", fb4_query)
    raw_responses = await client.search(fb4_query, timeout_secs=timeout_secs, response_limit=150)
    if is_cancelled():
        return [], False, True
    ranked, is_fallback = rank_responses(raw_responses, track, scorer, max_duration_diff=120)
    if ranked:
        logger.info("Artist-keyword fallback hit: '%s'", fb4_query)
    return ranked, is_fallback, False

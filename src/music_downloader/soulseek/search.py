"""slskd search lifecycle: start, poll, stop on timeout, collect partial results."""

import asyncio
import contextlib
import logging
import time

import requests.exceptions

from music_downloader.soulseek.errors import SlskdUnavailableError

logger = logging.getLogger(__name__)


class SearchLifecycle:
    """Runs slskd searches: search_text -> poll state -> stop -> collect -> delete.

    All synchronous slskd API calls are run in a thread executor so they
    don't block the event loop.
    """

    def __init__(self, api):
        self._api = api
        self._active_ids: set[str] = set()
        self._start_lock = asyncio.Lock()

    async def run(self, query: str, timeout_secs: int = 30, response_limit: int = 500) -> list[dict]:
        """Start a search and wait for results.

        On timeout the search is explicitly stopped and whatever partial
        results arrived are returned.
        """
        # Per-call holder so concurrent searches can't clobber each other's id.
        search_id_holder: list[str] = []

        try:
            return await asyncio.wait_for(
                self._poll(query, timeout_secs, response_limit, search_id_holder),
                timeout=timeout_secs + 10,
            )
        except TimeoutError:
            logger.warning(f"Hard timeout hit for search: {query}")
            if search_id_holder:
                return await self._stop_and_collect(search_id_holder[0])
            return []
        except requests.exceptions.RequestException as exc:
            logger.exception(f"slskd search failed for: {query}")
            raise SlskdUnavailableError(f"slskd API unreachable: {exc}") from exc
        except Exception:
            logger.exception(f"slskd search failed for: {query}")
            return []

    async def _cleanup_stale(self):
        """Delete old searches that this client is not currently running."""
        try:
            existing = await asyncio.to_thread(self._api.searches.get_all)
            if existing:
                active = set(self._active_ids)
                stale = [s for s in existing if s.get("id") not in active]
                logger.debug("Cleaning %d stale searches (keeping %d in-flight)", len(stale), len(active))
                for s in stale:
                    with contextlib.suppress(requests.exceptions.RequestException, KeyError):
                        await asyncio.to_thread(self._api.searches.delete, id=s["id"])
        except Exception:
            logger.warning("Failed to clean stale searches", exc_info=True)

    async def _poll(
        self, query: str, timeout_secs: int, response_limit: int, search_id_holder: list[str] | None = None
    ) -> list[dict]:
        """Core search logic with polling, stop-on-timeout, and partial results."""
        async with self._start_lock:
            await self._cleanup_stale()
            search_state = await asyncio.to_thread(
                self._api.searches.search_text,
                searchText=query,
                searchTimeout=timeout_secs * 1000,
                responseLimit=response_limit,
            )
            search_id = search_state["id"]
            if search_id_holder is not None:
                search_id_holder.append(search_id)
            self._active_ids.add(search_id)
        logger.info(f"Search started: id={search_id}, query='{query}'")

        min_wait = 5
        try:
            try:
                start = time.time()
                last_count = 0
                stable_since: float | None = None

                while time.time() - start < timeout_secs:
                    await asyncio.sleep(2)
                    state = await asyncio.to_thread(self._api.searches.state, id=search_id)

                    current_count = state.get("fileCount", 0)
                    resp_count = state.get("responseCount", 0)
                    is_complete = state.get("isComplete", False)
                    elapsed = time.time() - start

                    if current_count != last_count:
                        last_count = current_count
                        stable_since = time.time()
                        logger.debug(f"Search progress: {current_count} files from {resp_count} peers")
                    elif stable_since and (time.time() - stable_since > 8):
                        logger.info(f"Search stabilized with {current_count} files from {resp_count} peers")
                        break

                    if is_complete and elapsed >= min_wait:
                        logger.info(f"Search completed with {current_count} files from {resp_count} peers")
                        break
                else:
                    logger.info(
                        f"Search polling timeout ({timeout_secs}s) for '{query}', stopping and grabbing partial results"
                    )

            except Exception:
                logger.exception(f"Error during search polling for: {query}")

            with contextlib.suppress(requests.exceptions.RequestException):
                await asyncio.to_thread(self._api.searches.stop, id=search_id)

            responses = await self._collect_responses(search_id)

            with contextlib.suppress(requests.exceptions.RequestException):
                await asyncio.to_thread(self._api.searches.delete, id=search_id)
            return responses
        finally:
            self._active_ids.discard(search_id)

    async def _collect_responses(self, search_id: str) -> list[dict]:
        """Read final responses, falling back to the search_responses endpoint."""
        final_state = await asyncio.to_thread(
            self._api.searches.state,
            id=search_id,
            includeResponses=True,
        )
        responses: list[dict] = final_state.get("responses", [])

        if not responses:
            resp_count = final_state.get("responseCount", 0)
            file_count = final_state.get("fileCount", 0)
            if resp_count > 0 or file_count > 0:
                logger.info(
                    "state(includeResponses) empty despite %d peers / %d files — "
                    "falling back to search_responses endpoint",
                    resp_count,
                    file_count,
                )
                with contextlib.suppress(requests.exceptions.RequestException):
                    responses = await asyncio.to_thread(
                        self._api.searches.search_responses,
                        id=search_id,
                    )
                logger.info("search_responses returned %d responses", len(responses))
        return responses

    async def _stop_and_collect(self, search_id: str) -> list[dict]:
        """Stop a search and return whatever partial results exist."""
        with contextlib.suppress(requests.exceptions.RequestException):
            await asyncio.to_thread(self._api.searches.stop, id=search_id)
        try:
            responses = await self._collect_responses(search_id)
        except Exception:
            logger.exception(f"Failed to collect partial results for {search_id}")
            responses = []
        with contextlib.suppress(requests.exceptions.RequestException):
            await asyncio.to_thread(self._api.searches.delete, id=search_id)
        self._active_ids.discard(search_id)
        return responses

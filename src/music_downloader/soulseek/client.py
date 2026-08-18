"""slskd API client for searching and downloading files from Soulseek."""

import asyncio
import contextlib
import logging
import time

import requests.exceptions
import slskd_api

from music_downloader.soulseek.result import DownloadStatus, SearchResult

logger = logging.getLogger(__name__)


class SlskdUnavailableError(Exception):
    """Raised when the slskd API is unreachable (network/connection errors)."""


class SlskdClient:
    """Wrapper around slskd-api for search and download operations."""

    AUDIO_EXTENSIONS = {"flac", "alac", "wav", "aiff", "mp3", "aac", "m4a", "ogg", "opus", "wma"}

    def __init__(self, host: str, api_key: str):
        self.client = slskd_api.SlskdClient(host, api_key)
        self._current_search_id: str | None = None
        self._active_search_ids: set[str] = set()
        self._search_start_lock = asyncio.Lock()
        logger.info(f"slskd client initialized for {host}")

    async def search(self, query: str, timeout_secs: int = 30, response_limit: int = 500) -> list[dict]:
        """
        Start a search on slskd and wait for results.

        All synchronous slskd API calls are run in a thread executor so they
        don't block the event loop.  On timeout the search is explicitly
        stopped and whatever partial results arrived are returned.
        """
        self._current_search_id = None

        try:
            return await asyncio.wait_for(
                self._search_inner(query, timeout_secs, response_limit),
                timeout=timeout_secs + 10,
            )
        except TimeoutError:
            logger.warning(f"Hard timeout hit for search: {query}")
            search_id = self._current_search_id
            if search_id:
                return await self._stop_and_collect(search_id)
            return []
        except requests.exceptions.RequestException as exc:
            logger.exception(f"slskd search failed for: {query}")
            raise SlskdUnavailableError(f"slskd API unreachable: {exc}") from exc
        except Exception:
            logger.exception(f"slskd search failed for: {query}")
            return []

    async def _cleanup_stale_searches(self):
        """Delete old searches that this client is not currently running."""
        try:
            existing = await asyncio.to_thread(self.client.searches.get_all)
            if existing:
                active = set(self._active_search_ids)
                stale = [s for s in existing if s.get("id") not in active]
                logger.debug("Cleaning %d stale searches (keeping %d in-flight)", len(stale), len(active))
                for s in stale:
                    with contextlib.suppress(requests.exceptions.RequestException, KeyError):
                        await asyncio.to_thread(self.client.searches.delete, id=s["id"])
        except Exception:
            logger.warning("Failed to clean stale searches", exc_info=True)

    async def _search_inner(self, query: str, timeout_secs: int, response_limit: int) -> list[dict]:
        """Core search logic with polling, stop-on-timeout, and partial results."""
        async with self._search_start_lock:
            await self._cleanup_stale_searches()
            search_state = await asyncio.to_thread(
                self.client.searches.search_text,
                searchText=query,
                searchTimeout=timeout_secs * 1000,
                responseLimit=response_limit,
            )
            search_id = search_state["id"]
            self._current_search_id = search_id
            self._active_search_ids.add(search_id)
        logger.info(f"Search started: id={search_id}, query='{query}'")

        min_wait = 5
        try:
            try:
                start = time.time()
                last_count = 0
                stable_since: float | None = None

                while time.time() - start < timeout_secs:
                    await asyncio.sleep(2)
                    state = await asyncio.to_thread(self.client.searches.state, id=search_id)

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
                await asyncio.to_thread(self.client.searches.stop, id=search_id)

            final_state = await asyncio.to_thread(
                self.client.searches.state,
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
                            self.client.searches.search_responses,
                            id=search_id,
                        )
                    logger.info("search_responses returned %d responses", len(responses))

            with contextlib.suppress(requests.exceptions.RequestException):
                await asyncio.to_thread(self.client.searches.delete, id=search_id)
            return responses
        finally:
            self._active_search_ids.discard(search_id)

    async def _stop_and_collect(self, search_id: str) -> list[dict]:
        """Stop a search and return whatever partial results exist."""
        with contextlib.suppress(requests.exceptions.RequestException):
            await asyncio.to_thread(self.client.searches.stop, id=search_id)
        try:
            final_state = await asyncio.to_thread(
                self.client.searches.state,
                id=search_id,
                includeResponses=True,
            )
            responses: list[dict] = final_state.get("responses", [])
            if not responses and final_state.get("responseCount", 0) > 0:
                with contextlib.suppress(requests.exceptions.RequestException):
                    responses = await asyncio.to_thread(
                        self.client.searches.search_responses,
                        id=search_id,
                    )
        except Exception:
            logger.exception(f"Failed to collect partial results for {search_id}")
            responses = []
        with contextlib.suppress(requests.exceptions.RequestException):
            await asyncio.to_thread(self.client.searches.delete, id=search_id)
        self._active_search_ids.discard(search_id)
        return responses

    def parse_results(self, responses: list[dict], flac_only: bool = True) -> list[SearchResult]:
        """Parse raw slskd search responses into SearchResult objects."""
        results = []
        allowed = {"flac"} if flac_only else self.AUDIO_EXTENSIONS

        for response in responses:
            username = response.get("username", "")
            has_free_slot = response.get("hasFreeUploadSlot", False)
            upload_speed = response.get("uploadSpeed", 0)
            queue_length = response.get("queueLength", 0)

            for f in response.get("files", []):
                filename = f.get("filename", "")
                extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

                if extension not in allowed:
                    continue

                results.append(
                    SearchResult(
                        username=username,
                        filename=filename,
                        size=f.get("size", 0),
                        bit_rate=f.get("bitRate"),
                        bit_depth=f.get("bitDepth"),
                        sample_rate=f.get("sampleRate"),
                        length=f.get("length"),
                        has_free_slot=has_free_slot,
                        upload_speed=upload_speed,
                        queue_length=queue_length,
                    )
                )

        label = "FLAC" if flac_only else "audio"
        logger.info(f"Parsed {len(results)} {label} results from {len(responses)} responses")
        return results

    def enqueue_download(self, result: SearchResult) -> bool:
        """Enqueue a file for download via slskd."""
        try:
            files = [{"filename": result.filename, "size": result.size}]
            self.client.transfers.enqueue(username=result.username, files=files)
            logger.info(f"Enqueued download: {result.basename} from {result.username}")
            return True
        except Exception:
            logger.exception(f"Failed to enqueue download: {result.basename}")
            return False

    def get_download_status(self, username: str, filename: str) -> DownloadStatus | None:
        """Get the download status for a specific file."""
        try:
            downloads = self.client.transfers.get_downloads(username=username)

            if not downloads:
                return None

            for directory in downloads.get("directories", []):
                for transfer in directory.get("files", []):
                    if transfer.get("filename") == filename:
                        return DownloadStatus(
                            username=username,
                            filename=filename,
                            state=transfer.get("state", "Unknown"),
                            percent_complete=transfer.get("percentComplete", 0),
                            bytes_transferred=transfer.get("bytesTransferred", 0),
                            size=transfer.get("size", 0),
                            average_speed=transfer.get("averageSpeed", 0),
                            transfer_id=str(transfer["id"]) if transfer.get("id") is not None else None,
                        )

            return None

        except Exception:
            logger.exception(f"Failed to get download status for {filename}")
            return None

    async def wait_for_download(self, username: str, filename: str, timeout_secs: int = 600) -> DownloadStatus | None:
        """Wait for a download to complete, polling periodically."""
        start = time.time()

        while time.time() - start < timeout_secs:
            await asyncio.sleep(3)
            status = await asyncio.to_thread(self.get_download_status, username, filename)

            if status is None:
                logger.debug(f"No status yet for {filename}")
                continue

            if status.is_complete:
                logger.info(f"Download complete: {filename}")
                return status

            if status.is_failed:
                logger.warning(f"Download failed ({status.state}): {filename}")
                return status

            logger.debug(f"Download {status.percent_complete:.0f}%: {filename}")

        logger.warning(f"Download timed out after {timeout_secs}s: {filename}")
        return None

    def cancel_transfer(self, username: str, filename: str, transfer_id: str | None = None) -> bool:
        """Cancel an in-flight slskd download and remove it from the transfer list."""
        try:
            tid = transfer_id
            if not tid:
                status = self.get_download_status(username, filename)
                tid = status.transfer_id if status else None
            if not tid:
                logger.warning("No slskd transfer id to cancel for %s / %s", username, filename)
                return False
            self.client.transfers.cancel_download(username=username, id=tid, remove=True)
            logger.info("Cancelled slskd transfer %s (%s from %s)", tid, filename, username)
            return True
        except Exception:
            logger.exception("Failed to cancel slskd transfer for %s", filename)
            return False

    def ping(self) -> bool:
        """Return True if the slskd application API is reachable."""
        try:
            self.client.application.state()
            return True
        except Exception:
            logger.debug("slskd ping failed", exc_info=True)
            return False

    def get_downloads_directory(self) -> list[dict]:
        """Get the contents of the slskd downloads directory."""
        try:
            return self.client.files.get_downloads_dir()
        except Exception:
            logger.exception("Failed to list downloads directory")
            return []

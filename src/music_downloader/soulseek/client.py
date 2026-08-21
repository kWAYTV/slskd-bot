"""slskd API façade composing search, transfer, and remote file operations."""

import logging

import slskd_api

from music_downloader.soulseek import files, transfers
from music_downloader.soulseek.parsing import parse_search_responses
from music_downloader.soulseek.result import DownloadStatus, SearchResult
from music_downloader.soulseek.search import SearchLifecycle

logger = logging.getLogger(__name__)


class SlskdClient:
    """Single entry point for slskd: searches, transfers, and remote files."""

    def __init__(self, host: str, api_key: str):
        self.client = slskd_api.SlskdClient(host, api_key)
        self.searches = SearchLifecycle(self.client)
        logger.info(f"slskd client initialized for {host}")

    async def search(self, query: str, timeout_secs: int = 30, response_limit: int = 500) -> list[dict]:
        """Start a search on slskd and wait for (possibly partial) results."""
        return await self.searches.run(query, timeout_secs=timeout_secs, response_limit=response_limit)

    def parse_results(self, responses: list[dict], flac_only: bool = True) -> list[SearchResult]:
        """Parse raw slskd search responses into SearchResult objects."""
        return parse_search_responses(responses, flac_only=flac_only)

    def enqueue_download(self, result: SearchResult) -> bool:
        """Enqueue a file for download via slskd."""
        return transfers.enqueue(self.client, result)

    def get_download_status(self, username: str, filename: str) -> DownloadStatus | None:
        """Get the download status for a specific file."""
        return transfers.get_status(self.client, username, filename)

    async def wait_for_download(
        self,
        username: str,
        filename: str,
        timeout_secs: int = 600,
        progress_callback=None,
    ) -> DownloadStatus | None:
        """Wait for a download to complete, reporting progress via the callback."""
        return await transfers.wait_for_completion(
            self.get_download_status,
            username,
            filename,
            timeout_secs=timeout_secs,
            progress_callback=progress_callback,
        )

    def cancel_transfer(self, username: str, filename: str, transfer_id: str | None = None) -> bool:
        """Cancel an in-flight slskd download and remove it from the transfer list."""
        return transfers.cancel(self.client, self.get_download_status, username, filename, transfer_id)

    def delete_downloaded_file(self, relative_path: str) -> bool:
        """Delete a file inside slskd's downloads directory via remote file management."""
        return files.delete_downloaded_file(self.client, relative_path)

    def delete_downloaded_directory(self, relative_dir: str) -> bool:
        """Delete a subdirectory inside slskd's downloads directory."""
        return files.delete_downloaded_directory(self.client, relative_dir)

    def get_downloads_directory(self) -> list[dict]:
        """Get the contents of the slskd downloads directory."""
        return files.list_downloads_directory(self.client)

    def ping(self) -> bool:
        """Return True if the slskd application API is reachable."""
        try:
            self.client.application.state()
            return True
        except Exception:
            logger.debug("slskd ping failed", exc_info=True)
            return False

"""Gated Soulseek fetch for the library sweep: download, locate, spectrum gate."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from slskd_importer.library.files import FileProcessor
from slskd_importer.library.lossless import CHECKABLE_EXTENSIONS, analyze_lossless
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.result import SearchResult

logger = logging.getLogger(__name__)

ALL_REJECTED = "all copies failed the lossless gate"


@dataclass
class FetchOutcome:
    path: str | None = None
    transfer_id: str | None = None
    error: str = ""
    verdict_cutoff: float | None = None

    @property
    def ok(self) -> bool:
        return bool(self.path) and not self.error


@dataclass
class Rejection:
    result: SearchResult
    index: int
    reason: str


@dataclass
class GatedFetch:
    outcome: FetchOutcome
    result: SearchResult
    index: int
    rejected: list[Rejection] = field(default_factory=list)


def lossy_source(cutoff_khz: float | None, extension: str) -> str | None:
    """Why a lossless download looks lossy-sourced; None when it passes."""
    if extension.lower().lstrip(".") not in CHECKABLE_EXTENSIONS:
        return f"not spectrum-checkable ({extension})"
    if cutoff_khz is None:
        return "spectrum check failed"
    if cutoff_khz < 16.0:
        return f"fake lossless (cutoff {cutoff_khz:.1f} kHz)"
    return None


async def discard(
    slskd: SlskdClient,
    processor: FileProcessor,
    path: str,
    username: str,
    transfer_id: str | None,
) -> None:
    """Delete a downloaded candidate (local file and slskd transfer)."""
    basename = os.path.basename(path)
    if transfer_id:
        await asyncio.to_thread(slskd.cancel_transfer, username, basename, transfer_id)
    if os.path.isfile(path):
        deleted = await asyncio.to_thread(processor.cleanup_download, path)
        if not deleted:
            rel = await asyncio.to_thread(processor.relative_download_path, path)
            if rel:
                await asyncio.to_thread(slskd.delete_downloaded_file, rel)


async def fetch_one(
    slskd: SlskdClient,
    processor: FileProcessor,
    result: SearchResult,
    timeout_secs: int,
) -> FetchOutcome:
    """Enqueue, wait, locate on disk, run spectrum check."""
    ok = await asyncio.to_thread(slskd.enqueue_download, result)
    if not ok:
        return FetchOutcome(error="enqueue failed")
    status = await slskd.wait_for_download(result.username, result.filename, timeout_secs=timeout_secs)
    if status is None or not status.is_complete:
        err = status.state if status else "timeout"
        await asyncio.to_thread(slskd.cancel_transfer, result.username, result.basename, None)
        return FetchOutcome(error=err or "download failed")
    path = await asyncio.to_thread(processor.find_downloaded_file, result.username, result.filename)
    if not path:
        return FetchOutcome(error="file not found on disk", transfer_id=status.transfer_id)
    verdict = await asyncio.to_thread(analyze_lossless, path)
    cutoff = verdict.cutoff_khz if verdict else None
    return FetchOutcome(path=path, transfer_id=status.transfer_id, verdict_cutoff=cutoff)


async def fetch_gated(
    slskd: SlskdClient,
    processor: FileProcessor,
    results: list[SearchResult],
    index: int,
    timeout_secs: int,
    max_rejections: int = 5,
) -> GatedFetch:
    """Fetch results[index]; while lossy-sourced, discard and try the next."""
    rejected: list[Rejection] = []
    while index < len(results):
        result = results[index]
        outcome = await fetch_one(slskd, processor, result, timeout_secs)
        if not outcome.ok:
            return GatedFetch(outcome, result, index, rejected)
        reason = lossy_source(outcome.verdict_cutoff, result.extension)
        if reason is None:
            return GatedFetch(outcome, result, index, rejected)
        logger.info("Lossless gate rejected %s from %s: %s", result.basename, result.username, reason)
        if outcome.path:
            await discard(slskd, processor, outcome.path, result.username, outcome.transfer_id)
        rejected.append(Rejection(result, index, reason))
        index += 1
        if len(rejected) >= max_rejections:
            break
    last = results[min(index, len(results) - 1)]
    return GatedFetch(FetchOutcome(error=ALL_REJECTED), last, max(0, index - 1), rejected)

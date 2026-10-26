"""Apply Keep mine / Take new / Keep both and purge parked originals."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time

from slskd_importer.records.sweep_models import (
    DECISION_KEEP_BOTH,
    DECISION_KEEP_MINE,
    DECISION_TAKE_NEW,
    DECISIONS,
    Replacement,
    Review,
)
from slskd_importer.sweep.outcomes import PARKED_SUFFIX, SweepError
from slskd_importer.sweep.place import free_path, place, replace_in_library

logger = logging.getLogger(__name__)


class DecideMixin:
    """Decision and purge methods mixed into LibrarySweep."""

    async def decide(self, review_id: int, decision: str) -> tuple[Review, str]:
        """Apply the owner's decision on a pair; returns the review and the library path it left.

        keep_mine deletes the proposal; take_new replaces the song with it (the
        song parked in .sweep-replaced); keep_both adds it as a song
        of its own under the review's both_name. Either keep marks the song
        declined: no other recording is proposed for it again. Raises
        SweepError when the pair is unknown or already decided.
        """
        if decision not in DECISIONS:
            raise SweepError(f"decision must be one of {', '.join(DECISIONS)}, not {decision!r}")
        async with self._decide_lock:
            review = self.repo.get_review(review_id)
            if review is None:
                raise SweepError(f"no pair {review_id}")
            if review.decision is not None:
                raise SweepError(f"{review.stem}: already decided ({review.decision})")
            if decision != DECISION_KEEP_MINE and not os.path.isfile(review.proposal_path):
                raise SweepError(f"{review.stem}: the proposal file is gone")
            now = time.time()
            self.repo.decide(review.id, decision, now)
            try:
                path = await asyncio.to_thread(self._apply, review, decision)
            except BaseException:
                self.repo.undecide(review.id)
                raise
            review.decision, review.decided_at = decision, now
            if decision in (DECISION_KEEP_MINE, DECISION_KEEP_BOTH):
                self.repo.mark_declined(review.stem, now)
            logger.info("Sweep pair %s (%s): %s -> %s", review.id, review.stem, decision, path)
            return review, path

    def find_pending(self, stem: str) -> Review | None:
        return self.repo.pending_review_for(stem)

    def _apply(self, review: Review, decision: str) -> str:
        if decision == DECISION_KEEP_MINE:
            with contextlib.suppress(FileNotFoundError):
                os.remove(review.proposal_path)
            return review.current_path
        if decision == DECISION_TAKE_NEW:
            if os.path.isfile(review.current_path):
                target, parked = replace_in_library(
                    review.current_path, review.proposal_path, review.proposal_ext, self.replaced_dir, move=True
                )
                self.repo.add_replacement(
                    Replacement(
                        stem=review.stem,
                        new_path=target,
                        parked_path=parked,
                        from_desc=review.current_desc,
                        to_desc=review.proposal_desc,
                        how=DECISION_TAKE_NEW,
                        run_id=review.run_id,
                    )
                )
            else:
                target = os.path.join(self.root, f"{review.stem}.{review.proposal_ext}")
                target = place(review.proposal_path, free_path(target), None, move=True)
            if self.config.library_sweep_keep_days == 0:
                self.purge_parked()
            return target
        # DECISION_KEEP_BOTH
        target = free_path(os.path.join(self.root, review.both_name))
        place(review.proposal_path, target, review.current_path, move=True)
        return target

    # ----------------------------------------------------------------- purge

    def purge_parked(self, now: float | None = None) -> int:
        """Delete parked originals older than LIBRARY_SWEEP_KEEP_DAYS (only files this sweep parked). Blocking.

        LIBRARY_SWEEP_KEEP_DAYS=never (keep_days None) deletes nothing.
        """
        if self.config.library_sweep_keep_days is None:
            return 0
        now = time.time() if now is None else now
        cutoff = now - self.config.library_sweep_keep_days * 86400
        purged = 0
        root = os.path.realpath(self.replaced_dir)
        for rep in self.repo.unpurged_before(cutoff):
            real = os.path.realpath(rep.parked_path)
            if not real.startswith(root + os.sep) or not real.endswith(PARKED_SUFFIX):
                logger.warning("Sweep: not purging %s, it is not a parked file", rep.parked_path)
                self.repo.mark_purged(rep.id, now)
                continue
            try:
                os.remove(real)
                purged += 1
                logger.info("Sweep: purged the parked original %s", rep.parked_path)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Sweep: could not purge %s", rep.parked_path, exc_info=True)
                continue
            self.repo.mark_purged(rep.id, now)
        return purged

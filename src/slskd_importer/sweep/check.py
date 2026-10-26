"""Per-song sweep check: search, gated fetch, consider, stage, far-hold."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.library.formats import LOSSY_EXTENSIONS
from slskd_importer.records.sweep_models import Review, SweepRun, SweepSong
from slskd_importer.soulseek.fallbacks import search_with_fallbacks
from slskd_importer.sweep import audit as rules
from slskd_importer.sweep import fingerprint as fp
from slskd_importer.sweep import judge
from slskd_importer.sweep import sound as sound_mod
from slskd_importer.sweep.audit import Audit
from slskd_importer.sweep.fetch import discard, fetch_gated
from slskd_importer.sweep.outcomes import (
    CD_TRIES,
    OTHER_TRIES,
    OUTCOME_HIRES,
    OUTCOME_NO_BETTER_COPY,
    OUTCOME_NO_MATCH,
    OUTCOME_NONE_QUALIFIED,
    OUTCOME_REVIEW,
    OUTCOME_SKIPPED,
    OUTCOME_WAITING,
    PARKED_SUFFIX,
    REPAIRS,
    SAME_AND_BETTER,
    SongResult,
    _Held,
)
from slskd_importer.sweep.place import (
    _make_library_dir,
    carry_tags_and_cover,
    free_path,
    match_owner,
)
from slskd_importer.sweep.resolve import resolve_match

logger = logging.getLogger(__name__)


async def _no_progress(_status) -> None:
    return None



class CheckMixin:
    """Song check methods mixed into LibrarySweep."""

    async def check_song(self, path: str, song: SweepSong, original: Audit, run: SweepRun) -> SongResult:
        """Look for a better copy of one library song and act on what turns up."""
        stem = song.stem
        if self.repo.pending_review_for(stem) is not None:
            return SongResult(OUTCOME_WAITING, "a pair for this song waits for your ear")
        if original.tier == rules.TIER_HIRES and not run.force:
            return SongResult(OUTCOME_HIRES)
        artist, title = judge.split_stem(stem)
        if not artist:
            return SongResult(OUTCOME_SKIPPED, "name is not Artist - Title")

        candidates = await resolve_match(self.spotify, self.musicbrainz, artist, title, original.length or None)
        track: TrackInfo | None = next((c.track for c in candidates if c.confident), None)
        if track is None:
            return SongResult(OUTCOME_NO_MATCH, searched=True)
        ranked, _fallback, _cancelled = await search_with_fallbacks(
            self.slskd, self.scorer, track,
            timeout_secs=self.config.search_timeout_secs,
            is_cancelled=lambda: False,
        )
        if not ranked:
            # title-only already tried inside fallbacks; leave empty
            pass
        copies = [r for r in ranked if judge.wanted(original.tier, r, original.length)]
        if not copies:
            return SongResult(OUTCOME_NO_BETTER_COPY, searched=True)

        notes: list[str] = []
        tries = CD_TRIES if original.tier == rules.TIER_CD else OTHER_TRIES
        index = 0
        held: _Held | None = None
        try:
            while index < len(copies) and tries > 0:
                tries -= 1

                gated = await fetch_gated(
                    self.slskd, self.processor, copies, index,
                    timeout_secs=self.config.download_timeout_secs,
                )
                index = gated.index + 1
                outcome, result = gated.outcome, gated.result
                notes.extend(f"{r.result.basename}: {r.reason}" for r in gated.rejected)
                if not outcome.ok or not outcome.path:
                    notes.append(f"{result.basename}: {outcome.error}")
                    continue
                kept, detail, far = await self._consider(
                    path, stem, original, outcome.path, result, outcome.transfer_id, track, run
                )
                if kept is not None:
                    return SongResult(kept, detail, searched=True)
                if far is not None:
                    if held is None or far.similarity > held.similarity:
                        held, far = far, held
                    if far is not None:
                        await self._drop(far)
                notes.append(f"{result.basename}: {detail}")
            if held is not None:
                why = f"{held.why}, the only copy found"
                await self._stage(
                    run, stem, path, original, held.cand_path, held.cand, why, held.similarity, held.mine, held.theirs
                )
                return SongResult(OUTCOME_REVIEW, why, searched=True)
        finally:
            if held is not None:
                await self._drop(held)
        return SongResult(OUTCOME_NONE_QUALIFIED, "; ".join(notes)[:500], searched=True)

    async def _drop(self, held: _Held) -> None:
        """Delete a held copy's download."""
        if os.path.exists(held.cand_path):
            await discard(self.slskd, self.processor, held.cand_path, held.result.username, held.transfer_id)
        else:
            await asyncio.to_thread(self.slskd.cancel_transfer, held.result.username, held.result.basename, held.transfer_id)

    async def _consider(
        self, path, stem, original: Audit, cand_path, result, transfer_id, track, run
    ) -> tuple[str | None, str, _Held | None]:
        """Judge one downloaded copy; stage it for the owner's ear or discard it. Nothing is replaced without asking.

        Returns (OUTCOME_REVIEW, detail, None), (None, why it was discarded, None), or for a copy that
        qualifies but is another performance (fingerprint under FAR_SIMILARITY) (None, detail, the copy
        set aside): its download is kept for check_song to offer when no closer copy turns up. Otherwise
        the download is deleted from DOWNLOAD_DIR whatever happens.
        """
        held: _Held | None = None
        try:
            cand = await asyncio.to_thread(self.audit, cand_path)
            if not judge.better(original, cand):
                return None, f"not better ({rules.describe(cand)})", None
            similarity = await self._similarity(path, cand_path)
            kind, why = judge.judge(original, cand, stem, similarity)
            if kind == judge.REJECT:
                return None, f"rejected: {why}", None
            if self.repo.is_declined(stem):
                return None, f"you kept your file over another proposal before ({why})", None
            mine = await asyncio.to_thread(self.sound, path)
            theirs = await asyncio.to_thread(self.sound, cand_path)
            worse = sound_mod.sounds_worse(mine, theirs, original_lossy=original.ext in LOSSY_EXTENSIONS)
            if worse:
                return None, f"sounds worse: {worse}", None
            if original.strict is False:
                gain = (
                    f"cutoff {cand.cutoff - original.cutoff:+.1f} kHz"
                    if original.cutoff is not None and cand.cutoff is not None
                    else "your cutoff unknown"
                )
                why = f"{REPAIRS}, {gain}: {why}"
            elif kind == judge.SAME:
                why = f"{SAME_AND_BETTER}: {why}"
            if similarity is not None and similarity < fp.FAR_SIMILARITY:
                held = _Held(cand_path, result, transfer_id, cand, why, similarity, mine, theirs)
                return None, f"another performance (fingerprint {similarity:.2f}), set aside for a closer copy", held
            await self._stage(run, stem, path, original, cand_path, cand, why, similarity, mine, theirs)
            return OUTCOME_REVIEW, why, None
        finally:
            if held is None:  # a held copy's download stays for check_song
                if os.path.exists(cand_path):
                    await discard(self.slskd, self.processor, cand_path, result.username, transfer_id)
                else:
                    await asyncio.to_thread(self.slskd.cancel_transfer, result.username, result.basename, transfer_id)

    async def _similarity(self, original: str, candidate: str) -> float | None:
        a = await asyncio.to_thread(self.fingerprint, original)
        b = await asyncio.to_thread(self.fingerprint, candidate) if a else None
        if not a or not b:
            return None
        return await asyncio.to_thread(fp.similarity, a, b)

    async def _stage(
        self, run, stem, path, original: Audit, cand_path, cand: Audit, why, similarity, mine=None, theirs=None
    ):
        await asyncio.to_thread(carry_tags_and_cover, path, cand_path)

        def stage() -> str:
            _make_library_dir(self.review_dir)
            staged = free_path(os.path.join(self.review_dir, f"{stem}.{cand.ext}{PARKED_SUFFIX}"))
            shutil.copyfile(cand_path, staged)
            match_owner(staged, path)
            return staged

        staged = await asyncio.to_thread(stage)
        both = judge.keep_both_name(
            stem, cand.ext, original, cand, lambda n: os.path.exists(os.path.join(self.root, n))
        )
        self.repo.add_review(
            Review(
                stem=stem,
                current_path=path,
                proposal_path=staged,
                proposal_ext=cand.ext,
                both_name=both,
                reason=why,
                current_desc=rules.describe(original),
                proposal_desc=rules.describe(cand),
                current_len=original.length,
                proposal_len=cand.length,
                current_cutoff=original.cutoff,
                proposal_cutoff=cand.cutoff,
                similarity=similarity,
                run_id=run.id,
                current_sound=sound_mod.describe_sound(mine),
                proposal_sound=sound_mod.describe_sound(theirs, mine),
            )
        )

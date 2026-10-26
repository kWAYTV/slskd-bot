"""Sweep outcomes, report types, and held far-copy state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from slskd_importer.records.sweep_models import Review, SweepRun
from slskd_importer.sweep.audit import Audit

OUTCOME_UPGRADED = "upgraded"
OUTCOME_REVIEW = "review"
OUTCOME_NONE_QUALIFIED = "none_qualified"
OUTCOME_NO_BETTER_COPY = "no_better_copy"
OUTCOME_NO_MATCH = "no_match"
OUTCOME_HIRES = "hires"
OUTCOME_WAITING = "review_waiting"
OUTCOME_SKIPPED = "skipped"
OUTCOME_ERROR = "error"
OUTCOME_LABELS = {
    OUTCOME_UPGRADED: "Upgraded",
    OUTCOME_REVIEW: "For your ear",
    OUTCOME_NONE_QUALIFIED: "Copies tried, none qualified",
    OUTCOME_NO_BETTER_COPY: "No better copy on Soulseek",
    OUTCOME_NO_MATCH: "No confident match",
    OUTCOME_HIRES: "Already hi-res",
    OUTCOME_WAITING: "Waiting for your ear",
    OUTCOME_SKIPPED: "Skipped (not named Artist - Title)",
    OUTCOME_ERROR: "Errors",
}

# The reason of a pair whose proposal is the same recording and better: the owner still decides.
SAME_AND_BETTER = "Same recording, better copy"
# The reason of a pair whose library file has decode errors: the proposal is first of all a repair
# (sweep_rules.better lets it through with a cutoff up to 0.5 kHz lower).
REPAIRS = "Repairs the decode errors in yours"

REPLACED_DIR = ".sweep-replaced"
REVIEW_DIR = ".sweep-review"
# Parked and staged files end in this, so nothing watching the library takes them for songs.
PARKED_SUFFIX = ".sweep"
# A CD-quality song is searched again after this long (hi-res: never; the rest: every sweep).
CD_RECHECK_SECS = 30 * 86400
# Copies downloaded per song at most: hi-res copies are big, so a CD song gets fewer.
CD_TRIES = 2
OTHER_TRIES = 3
# A running sweep row not written for this long belongs to a process that stopped.
STALE_RUN_SECS = 15 * 60
# While a song downloads, the run row is written at least this often (STALE_RUN_SECS reads it).
HEARTBEAT_SECS = 60
# The schedule loop wakes at least this often (purging parked originals).
LOOP_TICK_SECS = 3600


@dataclass
class SongResult:
    outcome: str
    detail: str = ""
    searched: bool = False


@dataclass
class _Held:
    """A downloaded copy of another performance (fingerprint under FAR_SIMILARITY), set aside while closer
    copies are tried; offered only when none qualifies."""

    cand_path: str
    result: object
    transfer_id: str
    cand: Audit
    why: str
    similarity: float
    mine: object
    theirs: object


@dataclass
class SweepReport:
    """What the owner is told: the run and every pair still waiting for the ear.

    *in_progress*: the schedule came round while a sweep was still running.
    """

    run: SweepRun
    reviews: list[Review] = field(default_factory=list)
    in_progress: bool = False


ReportHook = Callable[[SweepReport], Awaitable[None]]


class SweepError(Exception):
    """A decision that cannot be applied (unknown song, already decided, file gone)."""

"""Library sweep dataclasses and decision constants."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_INTERRUPTED = "interrupted"

DECISION_KEEP_MINE = "keep_mine"
DECISION_TAKE_NEW = "take_new"
DECISION_KEEP_BOTH = "keep_both"
DECISIONS = (DECISION_KEEP_MINE, DECISION_TAKE_NEW, DECISION_KEEP_BOTH)

DECLINE_REASONS = ("distorted", "muffled", "other_version", "other")


@dataclass
class SweepSong:
    """One library file: audit at size/mtime, last check, and decline state."""

    file: str
    stem: str
    size: int
    mtime: float
    tier: str
    audit: dict
    last_checked_at: float | None = None
    outcome: str | None = None
    detail: str = ""
    declined_at: float | None = None


@dataclass
class SweepRun:
    id: int | None = None
    trigger: str = "schedule"
    force: bool = False
    owner: str = "bot"
    status: str = RUN_RUNNING
    total: int = 0
    done: int = 0
    current: str = ""
    counts: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None


@dataclass
class Review:
    """A proposal for the owner's ear: library file vs staged candidate."""

    stem: str
    current_path: str
    proposal_path: str
    proposal_ext: str
    both_name: str
    reason: str
    current_desc: str = ""
    proposal_desc: str = ""
    current_len: float | None = None
    proposal_len: float | None = None
    current_cutoff: float | None = None
    proposal_cutoff: float | None = None
    similarity: float | None = None
    run_id: int | None = None
    current_sound: str = ""
    proposal_sound: str = ""
    decline_reason: str = ""
    id: int | None = None
    created_at: float = field(default_factory=time.time)
    offered_at: float | None = None
    decided_at: float | None = None
    decision: str | None = None


@dataclass
class Replacement:
    """A library file the sweep replaced; original parked until purged."""

    stem: str
    new_path: str
    parked_path: str
    from_desc: str
    to_desc: str
    how: str
    run_id: int | None = None
    id: int | None = None
    replaced_at: float = field(default_factory=time.time)
    purged_at: float | None = None

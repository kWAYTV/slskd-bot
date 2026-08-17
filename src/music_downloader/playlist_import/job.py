from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    pending = "pending"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class TrackStatus(StrEnum):
    pending = "pending"
    searching = "searching"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


@dataclass
class ImportJob:
    id: int
    chat_id: int
    spotify_url: str
    name: str
    total_tracks: int
    completed_tracks: int
    failed_tracks: int
    skipped_tracks: int
    status: str
    created_at: str
    updated_at: str


@dataclass
class ImportTrack:
    id: int
    job_id: int
    position: int
    artist: str
    title: str
    album: str
    duration_ms: int
    spotify_url: str
    year: str
    status: str
    error_message: str
    created_at: str
    updated_at: str

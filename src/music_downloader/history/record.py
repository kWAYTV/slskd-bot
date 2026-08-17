from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HistoryRecord:
    id: int
    artist: str
    title: str
    album: str
    filename: str
    source_user: str
    remote_path: str
    status: str
    duration_secs: int
    file_size: int
    created_at: str

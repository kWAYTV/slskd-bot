"""What a queue item is doing right now. Kept in memory only; the store holds the outcome."""

from __future__ import annotations

from dataclasses import dataclass

IDENTIFYING = "identifying"
SEARCHING = "searching"
DOWNLOADING = "downloading"
CHECKING = "checking"
SAVING = "saving"
SENDING = "sending"


@dataclass
class Progress:
    phase: str
    percent: float | None = None
    queued: bool = False  # waiting in the peer's upload queue

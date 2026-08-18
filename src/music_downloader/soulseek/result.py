"""Soulseek search and download value objects."""

from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single file result from a slskd search."""

    username: str
    filename: str  # Full remote path (e.g., "\\Music\\Artist\\Song.flac")
    size: int  # Bytes
    bit_rate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    length: int | None = None  # Duration in seconds
    has_free_slot: bool = False
    upload_speed: int = 0
    queue_length: int = 0
    score: float = 0.0  # Assigned by scorer

    @property
    def basename(self) -> str:
        """Extract filename from the full remote path (Windows or POSIX)."""
        return self.filename.replace("\\", "/").rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        """File extension in lowercase."""
        return self.basename.rsplit(".", 1)[-1].lower() if "." in self.basename else ""

    @property
    def duration_display(self) -> str:
        """Human-readable duration."""
        if not self.length:
            return "??:??"
        mins, secs = divmod(self.length, 60)
        return f"{mins}:{secs:02d}"

    @property
    def size_mb(self) -> float:
        """File size in MB."""
        return self.size / (1024 * 1024)

    @property
    def quality_display(self) -> str:
        """Human-readable quality info."""
        parts = []
        if self.bit_depth and self.sample_rate:
            parts.append(f"{self.bit_depth}bit/{self.sample_rate / 1000:.1f}kHz")
        if self.bit_rate:
            parts.append(f"{self.bit_rate}kbps")
        return ", ".join(parts) if parts else "FLAC"

    def __str__(self) -> str:
        return f"{self.basename} ({self.duration_display}, {self.quality_display}, {self.size_mb:.1f}MB)"


@dataclass
class DownloadStatus:
    """Status of a file download."""

    username: str
    filename: str
    state: str  # e.g., "Completed", "InProgress", "Queued", etc.
    percent_complete: float = 0.0
    bytes_transferred: int = 0
    size: int = 0
    average_speed: float = 0.0

    @property
    def is_complete(self) -> bool:
        # slskd returns comma-separated states like "Completed, Succeeded"
        state_lower = self.state.lower()
        return "completed" in state_lower or "succeeded" in state_lower

    @property
    def is_failed(self) -> bool:
        state_lower = self.state.lower()
        return any(kw in state_lower for kw in ("errored", "rejected", "timedout", "cancelled"))

    @property
    def is_active(self) -> bool:
        return not self.is_complete and not self.is_failed


@dataclass
class ActiveDownload:
    """Tracks a download request with its context."""

    search_result: SearchResult
    track_filename: str  # Desired output filename (e.g., "Artist - Title.flac")
    status: DownloadStatus | None = None
    local_path: str | None = None  # Path to the downloaded file on disk

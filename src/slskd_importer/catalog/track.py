"""Core track identity used across catalog, search, download, and library."""

from dataclasses import dataclass


@dataclass
class TrackInfo:
    """Resolved track metadata from a catalog source (typically Spotify)."""

    artist: str
    title: str
    album: str
    duration_ms: int
    spotify_url: str
    year: str

    @property
    def duration_secs(self) -> int:
        """Duration in whole seconds."""
        return self.duration_ms // 1000

    @property
    def duration_display(self) -> str:
        """Human-readable duration like '2:42'."""
        mins, secs = divmod(self.duration_secs, 60)
        return f"{mins}:{secs:02d}"

    @property
    def filename(self) -> str:
        """Standard filename: 'Artist - Title'."""
        return f"{self.artist} - {self.title}"

    def __str__(self) -> str:
        return f"{self.artist} - {self.title} ({self.duration_display})"

"""Soulseek client errors."""


class SlskdUnavailableError(Exception):
    """Raised when the slskd API is unreachable (network/connection errors)."""

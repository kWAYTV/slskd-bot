"""Process health-check endpoint."""

from music_downloader.health.server import HealthHandler, start_health_server

__all__ = ["HealthHandler", "start_health_server"]

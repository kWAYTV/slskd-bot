"""Process-wide logging setup."""

import logging

from music_downloader.settings.config import Config


def setup_logging(config: Config):
    """Configure logging for the application."""
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("spotipy").setLevel(logging.WARNING)

"""Process-wide logging setup."""

import logging

from slskd_importer.settings.config import Config

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that drown operational output at INFO/DEBUG.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "telegram",
    "telegram.ext",
    "spotipy",
    "asyncio",
    "h11",
    "hpack",
)


def setup_logging(config: Config) -> None:
    """Configure logging for the application.

    ``force=True`` replaces any earlier basicConfig (e.g. from a library)
    so LOG_LEVEL actually applies. Noisy HTTP/Telegram clients stay at
    WARNING so DEBUG of ``slskd_importer.*`` stays readable.
    """
    logging.basicConfig(
        level=config.log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        force=True,
    )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("slskd_importer").setLevel(config.log_level)

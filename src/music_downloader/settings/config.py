"""Application settings loaded from environment variables."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Configuration settings loaded from environment variables."""

    def __init__(self):
        """Initialize configuration from environment variables."""
        self.telegram_bot_token = self._get_required_env("TELEGRAM_BOT_TOKEN")

        # Optional: self-hosted Bot API server (github.com/tdlib/telegram-bot-api),
        # e.g. "http://telegram-bot-api:8081". Raises the upload limit from
        # 50 MB (cloud Bot API) to 2000 MB, so originals are sent untouched.
        self.telegram_api_base_url = os.getenv("TELEGRAM_API_BASE_URL", "").strip().rstrip("/")
        limit_mb = 2000 if self.telegram_api_base_url else 50
        self.telegram_file_limit = limit_mb * 1024 * 1024

        allowed_users_str = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        self.telegram_allowed_users = self._parse_id_set(allowed_users_str)

        library_users_str = os.getenv("TELEGRAM_LIBRARY_USERS", "")
        self.telegram_library_users = self._parse_id_set(library_users_str)

        self.spotify_client_id = self._get_required_env("SPOTIFY_CLIENT_ID")
        self.spotify_client_secret = self._get_required_env("SPOTIFY_CLIENT_SECRET")

        self.slskd_host = self._get_required_env("SLSKD_HOST")
        self.slskd_api_key = self._get_required_env("SLSKD_API_KEY")

        self.download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
        self.output_dir = os.getenv("OUTPUT_DIR", "/music")
        self.data_dir = os.getenv("DATA_DIR", "/data")

        self.auto_mode = os.getenv("AUTO_MODE", "false").lower() == "true"
        self.max_results = int(os.getenv("MAX_RESULTS", "5"))
        self.duration_tolerance_secs = int(os.getenv("DURATION_TOLERANCE_SECS", "5"))
        self.search_timeout_secs = int(os.getenv("SEARCH_TIMEOUT_SECS", "30"))
        self.download_timeout_secs = int(os.getenv("DOWNLOAD_TIMEOUT_SECS", "600"))

        exclude_kw = os.getenv(
            "EXCLUDE_KEYWORDS",
            "live,remix,acoustic,karaoke,instrumental,cover,demo,radio edit,tribute,remaster",
        )
        self.exclude_keywords = [kw.strip().lower() for kw in exclude_kw.split(",") if kw.strip()]

        self.filename_template = os.getenv("FILENAME_TEMPLATE", "{artist} - {title}")

        quality_pref = os.getenv("QUALITY_PREFERENCE", "hires").strip().lower()
        self.quality_preference = quality_pref if quality_pref in ("hires", "cd") else "hires"

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level == "WARN":
            log_level = "WARNING"
        self.log_level = getattr(logging, log_level, logging.INFO)

        self.health_port = int(os.getenv("HEALTH_PORT", "8080"))

        self._log_summary(limit_mb)

    def _log_summary(self, limit_mb: int) -> None:
        logger.info(
            "Config: download_dir=%s output_dir=%s data_dir=%s auto=%s quality=%s "
            "max_results=%s search_timeout=%ss download_timeout=%ss duration_tol=%ss file_limit=%sMB",
            self.download_dir,
            self.output_dir,
            self.data_dir,
            self.auto_mode,
            self.quality_preference,
            self.max_results,
            self.search_timeout_secs,
            self.download_timeout_secs,
            self.duration_tolerance_secs,
            limit_mb,
        )
        if self.telegram_api_base_url:
            logger.info("Local Bot API server at %s (file limit %sMB)", self.telegram_api_base_url, limit_mb)
        if self.auto_mode:
            logger.info("AUTO_MODE enabled — best match will be downloaded automatically")

        if self.telegram_allowed_users:
            logger.info("Bot restricted to %d allowed user(s)", len(self.telegram_allowed_users))
        else:
            logger.warning("TELEGRAM_ALLOWED_USERS is empty — bot will deny all commands until configured")

        if self.telegram_library_users:
            logger.info("Library save restricted to %d user(s)", len(self.telegram_library_users))
        else:
            logger.info("TELEGRAM_LIBRARY_USERS is empty — all allowed users can save to the library")

    def _get_required_env(self, key: str) -> str:
        """Get a required environment variable."""
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"Required environment variable '{key}' is not set. "
                "Please set it in your .env file or container environment."
            )
        return value

    @staticmethod
    def _parse_id_set(id_str: str) -> set[int]:
        """Parse comma-separated ID string into a set of integers."""
        if not id_str or not id_str.strip():
            return set()
        return {int(uid.strip()) for uid in id_str.split(",") if uid.strip()}

"""
Entry point for Music Downloader.
Can be run as: python -m music_downloader
"""

import argparse
import logging
import sys

from music_downloader import __version__
from music_downloader.health.server import HealthHandler, start_health_server
from music_downloader.settings import Config, setup_logging
from music_downloader.telegram.app import create_bot

logger = logging.getLogger(__name__)

# Re-exported for tests and the CLI health endpoint.
_start_health_server = start_health_server

__all__ = ["HealthHandler", "cmd_run", "main"]


def cmd_run(args):
    """Run the Telegram bot with health check endpoint."""
    config = Config()
    setup_logging(config)

    logger.info(f"Music Downloader v{__version__} starting...")

    start_health_server(config.health_port)
    logger.info(f"Health check endpoint running on port {config.health_port}")

    bot_app = create_bot(config)
    logger.info("Starting Telegram bot polling...")
    bot_app.run_polling(drop_pending_updates=True)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="slskd-importer",
        description="Automated music discovery and download via Telegram bot.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.add_parser("run", help="Start the bot and health server")

    args = parser.parse_args()

    if args.command is None:
        args.command = "run"

    if args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

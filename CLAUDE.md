# CLAUDE.md — telegram-slskd-local-bot

## Overview
Telegram bot that automates music discovery and download. Resolves track metadata from Spotify, searches and downloads FLAC files from Soulseek via slskd, renames them to `Artist - Title.flac`, and places them in a music library directory.

## Tech Stack
- Python 3.11+
- python-telegram-bot (Telegram Bot API)
- spotipy (Spotify Web API, Client Credentials flow)
- slskd-api (Soulseek/slskd REST API)
- stdlib `HTTPServer` (health check endpoint)
- mutagen (audio metadata)
- Docker (image: `ghcr.io/kwaytv/slskd-bot`)
- Published on PyPI
- pytest + pytest-asyncio for testing
- uv for dependency management
- ruff for linting/formatting

## Development
```bash
# Install
pip install -e ".[dev]"
# Or with uv
uv sync

# Lint and format (always run before committing)
ruff check src/ tests/
ruff format src/ tests/

# Test
pytest
# Or with uv
uv run pytest
```

Configuration via `.env` (see `.env.example`).

## Architecture

The package is organized by **what the app does** (Screaming Architecture), not by technical layers.

```
src/music_downloader/
  catalog/           # Track identity — Spotify lookup, playlists, TrackInfo
  soulseek/          # Find and fetch files — search, scoring, slskd client
  library/           # Organize the collection — rename, artwork, FLAC, previews
  history/           # Download history records
  playlist_import/   # Playlist/album import jobs
  records/           # Shared SQLite connection used by history + import
  telegram/          # Conversation delivery — commands, search, download, import
  settings/          # Environment configuration and logging
  health/            # Process health-check endpoint
```

Telegram is a delivery mechanism, not the domain. `telegram/app.py` composes `MusicBot` from focused conversation modules (`commands`, `search_flow`, `download_flow`, `import_flow`). Domain packages do not import Telegram.

- `scripts/` — utility scripts
- `tests/` — test suite
- `docker-compose.yml` — full stack deployment
- `Dockerfile` — container build
- `.pre-commit-config.yaml` — code quality hooks

## Scoring Algorithm

Search results are ranked by 4 factors (total 100 points):
1. **Duration match** (40 pts): Compared to Spotify reference duration
2. **Audio quality** (25 pts): Higher bit depth and sample rate score more (24/96 over CD 16/44.1)
3. **Source reliability** (20 pts): Free slots, upload speed, queue
4. **Filename relevance** (15 pts): Artist/title word matching

Exclude keywords filter out live/remix/etc unless the original title contains them.

## Soulseek (slskd) Search Patterns

- **Single query, local filtering**: Never append format keywords (e.g. "flac") to the slskd search query -- Soulseek matches keywords against full file paths, which is unreliable. Instead, search with `artist title` and filter results locally by file extension (`.flac` preferred, fall back to other audio formats)
- **Search lifecycle**: `search_text()` -> poll `state()` -> `stop()` on timeout -> grab partial results from `search_responses()` -> `delete()` cleanup
- **Async wrapping**: All synchronous `slskd-api` calls must be wrapped with `asyncio.to_thread()` to avoid blocking the Telegram bot event loop
- **Timeouts**: Hard timeout via `asyncio.wait_for()` around the entire search+poll loop; `searches.stop()` actively cancels the server-side search on timeout

## Telegram UX Patterns

- **Markdown escaping**: Dynamic text (filenames, paths from Soulseek) must be escaped with `_escape_md()` or wrapped in backtick code spans to avoid `BadRequest` from Telegram's Markdown parser
- **Safe edits**: Always use the `_safe_edit()` wrapper (catches `BadRequest`, `TimedOut`, `NetworkError`) instead of raw `msg.edit_text()`
- **Result identification**: Download messages must include `#number` labels matching the result list so users can tell concurrent downloads apart
- **Spotify results cap**: Show max 5 results to the user; fetch 10 from the API for filtering headroom
- **Spotify artist filter**: When query contains `artist - title`, filter Spotify results by artist substring match before dedup to remove noise; fall back to unfiltered if the filter empties the list

## Deployment

### Release Steps

1. Push to `main` — GHA `docker-publish.yml` builds and pushes `ghcr.io/kwaytv/slskd-bot:latest` (also `main-<sha>`)
2. Optional: create a **new** semver tag (e.g. `git tag v0.3.1`) and push with `--tags` for a versioned image
3. Pull with `docker pull ghcr.io/kwaytv/slskd-bot:latest`

### Versioning Rules

- **NEVER** force-retag an existing version. Each release gets a unique semver tag.
- **Patch** (`v0.3.0` -> `v0.3.1`): Bug fixes, UX tweaks, small changes
- **Minor** (`v0.3.x` -> `v0.4.0`): New features, significant behavior changes
- **Major** (`v0.x.y` -> `v1.0.0`): Breaking changes
- Check the latest tag before tagging: `git describe --tags --abbrev=0`

## External Dependencies

- **Spotify API**: Client Credentials flow (no user login). Used only for metadata resolution.
- **slskd API**: REST API with API key auth. Used for search, download, and file management.
- **Telegram Bot API**: Long-polling mode. Restricted to allowed user IDs via `TELEGRAM_ALLOWED_USERS`.

## Testing Strategy

- **Unit:** Scorer, config parsing, file handler, TrackInfo
- **Integration:** slskd client, Spotify resolver (with mocks)
- **Coverage target:** 80%

## Key Rules
- Never hardcode API keys (Telegram, Spotify, slskd); use environment variables
- Allowed Telegram users must be explicitly configured
- Docker images: `latest` on `main` pushes; semver tags on version releases
- License is GPL-3.0
- Follow PEP 8, use type hints, prefer f-strings
- Telegram bot: [@slskdimporterbot](https://t.me/slskdimporterbot)

*Generated by [LynxPrompt](https://lynxprompt.com) CLI*

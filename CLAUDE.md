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
src/slskd_importer/
  catalog/           # Track identity — Spotify lookup, playlists, TrackInfo
  soulseek/          # Find and fetch files — search lifecycle, transfers, ranking, fallbacks
  library/           # Organize the collection — rename, formats, artwork, FLAC, previews
  history/           # Download history records
  playlist_import/   # Playlist/album import jobs
  records/           # Shared SQLite connection used by history + import
  telegram/          # Conversation delivery (feature subpackages, see below)
  settings/          # Environment configuration and logging
  health/            # Process health-check endpoint
```

Telegram is a delivery mechanism, not the domain. The `telegram/` package contains only feature subpackages, each made of small single-purpose modules:

```
telegram/
  core/              # MusicBot composition root (app), callback routing, access, cleanup, session
  ui/                # markdown escaping, safe edits, text formatting, inline keyboards
  commands/          # basics (/start /help), preferences (/quality), activity (/status /history /stats /undo /cancel)
  search/            # text entry, pasted links, Spotify pick, Soulseek search, direct search, results
  download/          # selection, run (orchestration), transfer (shared pipeline + history), delivery (send/preview/artwork), approval, retry
  playlist_import/   # /import command, callbacks, job queue, per-track search/download, summary, resume
```

- `telegram/core/app.py` wires domain services into `MusicBot` and binds the conversation handlers from the feature modules as class attributes (handler functions take the bot as `self`)
- The shared download pipeline (`download/transfer.py`, `download/delivery.py`) and the save sequence (`download/approval.save_to_library`) are reused by the playlist import flow — never duplicate enqueue/wait/progress/save logic
- Soulseek search policy (FLAC-first ranking, four-tier query fallbacks) lives in `soulseek/scoring.py` and `soulseek/fallbacks.py`, not in the Telegram layer
- Domain packages do not import Telegram
- Audio format allow-list is defined once in `library/formats.py`

- `scripts/` — utility scripts
- `tests/` — test suite (mirrors `src/`: `tests/<package>/…`, `tests/telegram/<feature>/…`; shared mock builders live in `helpers.py` modules)
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
- **Cleanup**: Stale slskd searches are deleted only when their IDs are not in `_active_search_ids` (serialized with search start)
- **Import search**: Playlist import uses the same four-tier fallbacks as manual search (`search_with_fallbacks`)
- **Import resume**: Active jobs auto-resume on startup; `/import resume` continues the chat's pending/active job after resetting `searching` / `awaiting_approval` tracks
## Telegram UX Patterns

- **Markdown escaping**: Dynamic text (filenames, paths from Soulseek) must be escaped with `escape_md()` or wrapped in backtick code spans via `code_span()` / `md_code_safe()` (plain backtick wrapping breaks when the value itself contains a backtick) to avoid `BadRequest` from Telegram's Markdown parser
- **Safe edits**: Always use the `safe_edit()` / `safe_query_edit()` wrappers (catch `BadRequest`, `TimedOut`, `NetworkError`) instead of raw `msg.edit_text()`
- **Result identification**: Download messages must include `#number` labels matching the result list so users can tell concurrent downloads apart
- **Download progress**: `wait_for_download()` accepts an async `progress_callback`; conversation flows use it to edit the status message (throttled to ~10% steps or on transfer-state change) with a `progress_bar()` and update `PendingDownload.progress_percent` / `transfer_state` for `/status`
- **Quality preference**: `/quality` toggles CD-vs-Hi-Res ranking per chat (`MusicBot.quality_pref(chat_id)`); persisted in `chat_prefs`. `QUALITY_PREFERENCE` env is only the default. Scoring lives in `soulseek/scoring.py` (`_quality_points`)
- **Canonical tags**: `FileProcessor.process_file` writes artist/title/album/year via mutagen at save time
- **Import skip-owned**: `process_next_import_track` skips tracks already in the library (`find_exact`) or successful history (`find_success`)
- **Import progress**: one in-place status message per job (`_import_status_msg`); extra messages only when the user must act
- **Approval TTL**: `core/ttl.py` expires awaiting-approval downloads older than `APPROVAL_TTL_SECS` (default 24h)
- **Download concurrency**: `fetch_from_peer` takes `MusicBot._download_sem` (`MAX_CONCURRENT_DOWNLOADS`, default 3)
- **Pasted links**: `catalog/links.py` detects Spotify track links/URIs in free text; tracks resolve via `SpotifyResolver.get_track`. Playlist/album links start the import flow directly (library users only)
- **Duplicates**: `notify_if_already_owned` (in `search/soulseek.py`) sends a non-blocking "already in the library" notice after Spotify resolve; the search always continues
- **Direct search**: the "Search Soulseek directly" button searches immediately with artist/title parsed from the query (`parse_query_artist_title`) — no follow-up prompt
- **Undo**: `/undo` deletes the last chat save via `FileProcessor.delete_library_file` (refuses paths outside OUTPUT_DIR) and marks the history row `undone`
- **Large files**: the send limit is `Config.telegram_file_limit`, not a constant — 50MB on the cloud Bot API, 2000MB when `TELEGRAM_API_BASE_URL` points at a self-hosted `telegram-bot-api` server (wired via `base_url`/`base_file_url`/`local_mode` in `create_bot`). Over-limit files fall back to OGG Opus / preview clips in `delivery.send_large_file`
- **Spotify results cap**: Show 5 results per page to the user; fetch up to 50 from the API for filtering headroom
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
- **Telegram Bot API**: Long-polling mode. Restricted to allowed user IDs via `TELEGRAM_ALLOWED_USERS`. Library writes (save + `/import`) can be further restricted with `TELEGRAM_LIBRARY_USERS`.

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

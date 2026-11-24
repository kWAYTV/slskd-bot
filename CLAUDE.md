# CLAUDE.md — telegram-slskd-local-bot

## Overview
Telegram bot that gets music from Soulseek. Every chat message (song names, links, pasted tracklists) becomes a batch in a download queue; each track is identified against a catalog (Spotify), searched on Soulseek via slskd (FLAC, WAV, AIFF first), fetched, spectrum-checked, renamed to `Artist - Title` and placed in the library — or sent to the chat for people without library access. Nothing is confirmed by hand.

## Tech Stack
- Python 3.11+
- python-telegram-bot (Telegram Bot API)
- spotipy (Spotify Web API, Client Credentials flow)
- slskd-api (Soulseek/slskd REST API)
- stdlib `HTTPServer` (health check endpoint)
- mutagen (audio metadata)
- yt-dlp (metadata only: YouTube / SoundCloud / Bandcamp tracklists)
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

The package is organized by **what the app does** (Screaming Architecture), not by technical layers. A directory holds either modules or subpackages, never both (only `telegram/` holds subpackages).

```
src/slskd_importer/
  catalog/     # Track identity — TrackInfo, Spotify, MusicBrainz, query -> track lookup
  sources/     # What a message asks for — Spotify links, media pages (yt-dlp), tracklist pages, typed lines
  queue/       # The download queue — batches/items, store, runner, per-item pipeline, fetch, library shelf
  soulseek/    # Find and fetch files — search lifecycle, transfers, ranking, fallbacks
  library/     # The collection on disk — rename, tags, formats, ownership, lossless check, OGG conversion
  sweep/       # Library upgrade scout — audit, fingerprint, sound, judge, fetch, decide, schedule
  history/     # Download history records
  records/     # Shared SQLite (queue, history, prefs, sweep)
  telegram/    # Conversation delivery (feature subpackages, see below)
  settings/    # Environment configuration and logging
  health/      # Process health-check endpoint
```

How a request flows: `telegram/intake` reads the message with `sources.message.read_message` (a `Tracklist` of `Entry`s) and stores a batch → `queue.runner.QueueRunner` claims items fairly across batches → `queue.pipeline.ItemPipeline` runs each one (identify → owned? → search → fetch → lossless check → save or deliver) → the runner's `on_change` hook makes `telegram/card` redraw the batch's one message.

Telegram is a delivery mechanism, not the domain. `queue/` and `sources/` never import Telegram.

```
telegram/
  core/           # MusicBot composition root (app), callback routing, access
  intake/         # a chat message -> a queue batch + its card
  card/           # the batch's live message: views (summary, list, item, picker), button actions, redraw board
  delivery/       # sending track files to a chat (audio, document fallback, OGG when oversize)
  commands/       # one module per command: basics, preferences, status, stats, history, undo, cancel
  library_sweep/  # /sweep, review pairs, Keep mine reasons, schedule lifecycle
  ui/             # presentation primitives only — markdown, safe edits, reactions, reply-to
  i18n/           # per-locale string modules (en/es/gl/de) + thin catalog lookup
```

- `telegram/core/app.py` wires domain services into `MusicBot` and binds handlers from the feature modules as class attributes (handler functions take the bot as `self`)
- **Batch / item states** live in `queue/batch.py`. `working` is the only in-flight status in the store; the phase (searching, downloading 42%, checking…) is `queue.progress.Progress`, in memory on the runner
- **One pipeline**: enqueue/wait/locate is `queue/fetch.py`, placing and undoing is `queue/shelf.py`. Never duplicate that logic in the Telegram layer
- **Destination** (`Destination.library` / `Destination.deliver`) is fixed per batch at intake from `can_save_library(user)`. A `deliver` batch never calls the shelf's `place`; the pipeline's `deliver` hook (`telegram/delivery/handoff.deliver_copy`) sends the file
- **Every track is picked by hand by default**: after the search an item ends as `choose` and opens on the picker. Only with `AUTO_PICK=true` (`Config.auto_pick`) do lists fetch the best sure copy unasked; a song sent alone (`Batch.asks_which_copy`, kind `track`) always asks
- **Exceptions, not questions**: only-lossy results end as `review`, nothing found as `no_match`, all copies failing as `failed`. The requester acts from the card; a hand-picked copy (stored on the item as `queue_items.pick`, see `queue/pick.py`, so it survives a restart) is fetched as is, with no owned check and no fake-lossless gate
- **Sources return text** unless they know the catalog identity: only Spotify builds `TrackInfo`. Media pages and tracklists yield `Entry(query="Artist - Title")` and never carry durations (video lengths would break duration scoring)
- **Sweep scope**: `LibrarySweep.root` is `Config.library_sweep_dir` and is walked recursively (`sweep.place.library_files`, hidden folders skipped). A song's `file` / `stem` are its path under that root with forward slashes; use `sweep.identity.leaf(stem)` wherever only the file name is meant (identity, judging, staged names)
- Soulseek search policy (FLAC → WAV → AIFF, then any audio; four-tier query fallbacks) lives in `soulseek/scoring.py` and `soulseek/fallbacks.py`
- Audio format allow-list is defined once in `library/formats.py`

- `scripts/` — utility scripts
- `tests/` — test suite (mirrors `src/`: `tests/<package>/…`, `tests/telegram/<feature>/…`; shared builders live in `helpers.py` modules)
- `docker-compose.yml` — full stack deployment
- `Dockerfile` — container build
- `.pre-commit-config.yaml` — code quality hooks

## Scoring Algorithm

Search results are ranked by format first (FLAC → WAV → AIFF → other), then 4 score factors (total 100 points):
1. **Duration match** (40 pts): Compared to catalog reference duration
2. **Audio quality** (25 pts): Higher bit depth and sample rate score more (24/96 over CD 16/44.1)
3. **Source reliability** (20 pts): Free slots, upload speed, queue
4. **Filename relevance** (15 pts): Artist/title word matching

Exclude keywords filter out live/remix/etc unless the original title contains them.

## Soulseek (slskd) Search Patterns

- **Single query, local filtering**: Never append format keywords (e.g. "flac") to the slskd search query -- Soulseek matches keywords against full file paths, which is unreliable. Instead, search with `artist title` and filter results locally by file extension (`.flac` / `.wav` / `.aiff` preferred, fall back to other audio formats)
- **Search lifecycle**: `search_text()` -> poll `state()` -> `stop()` on timeout -> grab partial results from `search_responses()` -> `delete()` cleanup
- **Async wrapping**: All synchronous `slskd-api` calls must be wrapped with `asyncio.to_thread()` to avoid blocking the Telegram bot event loop
- **Timeouts**: Hard timeout via `asyncio.wait_for()` around the entire search+poll loop; `searches.stop()` actively cancels the server-side search on timeout
- **Cleanup**: Stale slskd searches are deleted only when their IDs are not in `_active_search_ids` (serialized with search start)
- **Queue search**: every queue item uses the four-tier fallbacks (`queue.copies.CopyFinder` → `search_with_fallbacks`) and remembers the top copies in the database (`queue_copies`, cached in memory) so the picker needs no second search, even after a restart
- **Failed transfers**: slskd reports failures as `Completed, Errored`; check `DownloadStatus.is_failed`, never `not is_complete`

## Telegram UX Patterns

- **One card per message**: a batch owns exactly one message (`queue_batches.message_id`), sent as a reply to the request. Everything after that is an edit of it. Do not send extra messages for progress or results; the only other messages are files delivered to the chat and command replies
- **Redraws** go through `card.board.CardBoard.request(batch_id)` (throttled, bursts collapse) or `draw()` right after a button tap. The board skips edits whose text and keyboard did not change and backs off on `RetryAfter`
- **Views** (`card/board.View`): summary, list, item, picker. A one-track batch always shows the item view. A track view remembers where it was opened from (`View.back`: summary or a list page, derived in `CardBoard.focus`); Back returns there, and so does `CardBoard.leave()` after an action that finishes with the track (pick, skip, retry). A `choose` track opens straight on the picker (`card.status.open_action`). View state is in memory; after a restart cards fall back to the summary
- **Buttons**: callback data is `q:<action>:<batch>:<item>:<number>` (`card/actions.py`). `core/routing` dispatches by prefix (`q`, `hu`, `cu`, `swp`, `swr`, `cancel_all`, `lang`) and answers every tap, with a toast for the ones that start work
- **Batch ownership**: card callbacks load the batch with `get_batch_for_chat`, so a button can never reach another chat's queue. Undo and replacing a saved track also need `can_save_library`
- **Markdown escaping**: Dynamic text (filenames, paths from Soulseek, item details) must be escaped with `escape_md()` or wrapped via `code_span()` / `md_code_safe()` to avoid `BadRequest` from Telegram's legacy Markdown parser
- **Safe edits**: use `safe_edit()` / `safe_query_edit()` / `safe_bot_edit()` (catch `BadRequest`, `TimedOut`, `NetworkError`; "message is not modified" counts as success) instead of raw edits
- **Feedback without messages** (`ui/feedback.py`, all errors swallowed): the request message is reacted 👀 at intake and 👍 / 🤷 by the board when the batch finishes (Telegram's fixed reaction set has no ✅); `show_typing` / `show_uploading` bracket lookups and uploads
- **Startup**: `basics.register_bot_commands` sets the command menu and the per-locale descriptions (`bot_description` ≤ 512 chars, `bot_short_description` ≤ 120); `runner.start()` requeues items a restart interrupted and every active batch's card is redrawn
- **Concurrency**: `Application.concurrent_updates(True)` — a button that searches (the picker) must not block other updates. `QueueRunner` runs at most `MAX_CONCURRENT_DOWNLOADS` items; `QueueRepository.claim_next` prefers the batch with the fewest items in flight
- **Owned check**: `LibraryShelf.owned_as` — an exact file name in the save folder, a past successful save whose file still exists, or a file named `Artist - Title` anywhere under `LIBRARY_SWEEP_DIR` (`library/index.LibraryIndex`: file names only, cached two minutes, `DOWNLOAD_DIR` and hidden folders excluded, versions kept apart). Skipped for `forced` items (*Download anyway*) and for delivery batches
- **Parked transfers**: an item whose transfer waits in a peer's upload queue (`Progress.queued`) does not count against the worker slots (`QueueRunner._has_free_slot`), up to `runner.MAX_PARKED`
- **Peer queues**: an automatically chosen copy that stays queued at its peer for `pipeline.QUEUE_PATIENCE_SECS` is dropped for the next copy (`queue/fetch.py`); a hand-picked copy may wait `PICKED_QUEUE_PATIENCE_SECS` in the queue. `DOWNLOAD_TIMEOUT_SECS` only limits a transfer that is running
- **Doubted copies** (`ItemStatus.doubt`): a copy saved to the library whose verdict is not `AUTHENTIC` is in `ATTENTION` until the requester keeps it (`done`), picks another (replaced on success) or undoes it. `SAVED_STATUSES` (`done`, `doubt`) is what "the file is in the library" means everywhere
- **Lossless gate**: a checkable lossless copy whose spectrum verdict is `FAKE` is discarded and the next copy tried, up to `pipeline.MAX_TRIES`
- **The typed song wins** (`catalog/lookup.identify`): for an `Artist - Title` query a catalog candidate is used only when `catalog/names.same_artist` and `same_title` both hold; otherwise the track is built from the text. Never fall back to "first candidate" for separated queries
- **A copy must name the song** (`queue/confidence.py`, applied in `CopyFinder.find`): only copies whose remote path carries every title word and one artist word are kept, for the picker and for auto-pick alike; a track with none is `no_match`. `no_match` and `failed` are not in `card.status.ATTENTION`: they are counted and retryable together but never ask for a decision
- **Catalog lookup** (`catalog/lookup.py`): `Artist - Title` queries try `SpotifyResolver.search_fielded` first, free text as fallback; candidates are filtered by the named artist and editions of one recording collapsed (±2s, earliest year). No catalog match gives a duration-free track parsed from the text (`parse_query_artist_title`; `clean_query` strips `(Official Video)`-style noise)
- **Canonical tags**: `FileProcessor.process_file` writes artist/title/album/year via mutagen at save time; artwork is embedded by the shelf
- **Undo**: the card's Undo and `/undo` delete via `FileProcessor.delete_library_file` (refuses paths outside OUTPUT_DIR) and mark the history row `undone`
- **Large files**: the send limit is `Config.telegram_file_limit` — 50MB on the cloud Bot API, 2000MB when `TELEGRAM_API_BASE_URL` points at a self-hosted `telegram-bot-api` server. Over-limit files are sent as OGG Opus with a note (`delivery/send.py`)
- **i18n**: every user-facing string is a key in `i18n/en.py` mirrored in es/gl/de (a test enforces equal key sets). Exceptions: `SourceError` messages and item `detail` text come from the domain in English

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
- **Telegram Bot API**: Long-polling mode. Restricted to allowed user IDs via `TELEGRAM_ALLOWED_USERS`. `TELEGRAM_LIBRARY_USERS` narrows who saves to the library; other allowed users get files sent to their chat.

## Testing Strategy

- **Unit:** scorer, config parsing, file handler, sources (injected `extract` / `fetch`, no network), card views
- **Integration:** queue store/runner/pipeline against a real SQLite file with fake slskd; `MusicBot` with mocked Telegram
- **Coverage target:** 80%

## Key Rules
- Never hardcode API keys (Telegram, Spotify, slskd); use environment variables
- Allowed Telegram users must be explicitly configured
- Docker images: `latest` on `main` pushes; semver tags on version releases
- License is GPL-3.0
- Follow PEP 8, use type hints, prefer f-strings
- Telegram bot: [@slskdimporterbot](https://t.me/slskdimporterbot)

*Generated by [LynxPrompt](https://lynxprompt.com) CLI*

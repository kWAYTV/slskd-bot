# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- Auto mode (`/auto`, `AUTO_MODE`). Results always show a pick keyboard; "Auto-pick best" remains a one-click `#1`

### Changed

- Operational logging: millisecond timestamps, silenced noisy HTTP/Telegram clients, and lifecycle logs for search, download, approval, import, auth, and cancel
- Dependencies and CI pins refreshed (PTB 22.8, slskd-api 0.2.4, ruff 0.16.4, CodeQL Action 4.37.8, pre-commit-hooks v6)
- Schema v4 adds `chat_prefs` for persisted per-chat quality preference
- Playlist import uses a single in-place progress message instead of one message per track
- Search results show the remote parent folder so identical filenames are distinguishable
- Download progress and `/status` surface queued-at-peer state

### Added

- Canonical artist/title/album/year tags written on library save
- Playlist import skips tracks already in the library or successful history
- `/stats` — chat download totals, save rate, top sources, library size
- `/history` inline ↩️ buttons to undo a specific save
- Approval TTL (`APPROVAL_TTL_SECS`, default 24h) discards stale pending files
- Download concurrency cap (`MAX_CONCURRENT_DOWNLOADS`, default 3)
- Live download progress: the "Downloading" status message now updates with a percentage and progress bar (manual search and playlist import flows)
- `/status` shows per-download progress ("42%" / "awaiting approval") and the active playlist import with saved/failed/skipped counters
- `/auto` is now a per-chat toggle; the `AUTO_MODE` env var is only the default
- Retry and "try next result" messages carry the `#n` result label so concurrent downloads stay distinguishable
- Unexpected download errors now offer Retry / Try next result instead of a dead end
- i18n via GNU gettext + Babel: English, Spanish, German, and Galician. First-time users pick a language; `/lang` (or `/language`) changes it later
- Schema v3 adds `user_locales` for persisted language preference
- Auto-mode actually downloads the best match after a successful search
- Import download failures now offer Retry, Skip, and Mark failed (no longer stall)
- `/import` and `/cancel` documented in `/help` and README
- `/import resume` continues a persisted playlist import after a bot restart; active jobs auto-resume on startup
- `TELEGRAM_LIBRARY_USERS` restricts who can save into the music library or run `/import`. Other allowed users still receive the file via Telegram; the local copy is then deleted
- `/health` reports slskd reachability (`healthy` / `degraded`); `/ready` returns 503 when slskd is unreachable
- Approve keyboard offers "Try next result" when more Soulseek matches remain
- Exact duplicate check (library filename + successful history / Spotify URL) before searching Soulseek

### Fixed

- Soulseek filenames and usernames containing backticks no longer break Telegram Markdown code spans (`code_span()` / `md_code_safe()`)
- All download status edits go through `safe_edit()`, so transient Telegram errors can't crash an in-flight download
- In-flight downloads are registered immediately, so `/cancel` and `/status` see them before completion
- `/status` no longer crashes when a pending search has no resolved track
- `/status` is scoped to the current chat instead of leaking other users' activity
- Results keyboard is locked after picking a download (prevents duplicate parallel picks)
- Hard slskd search timeout now collects partial results instead of always returning empty
- Soulseek paths using `/` (not just `\\`) resolve to the correct basename
- Download enqueue and status polling no longer block the Telegram event loop
- Markdown-special characters in artist/title/album no longer break Telegram messages
- Empty `TELEGRAM_ALLOWED_USERS` documented as deny-all (matches runtime behavior)
- `MAX_RESULTS` default aligned to 5 across config, `.env.example`, and README
- Search cleanup no longer deletes in-flight slskd searches
- `/cancel` and generation bumps abort the slskd transfer (`cancel_download(..., remove=True)`) and delete partial files
- Import search uses the same four-tier fallbacks as manual search
- `/history` is scoped to the current chat
- Corrupt SQLite databases are renamed to `*.bak.<timestamp>` before recreate
- Schema v2 adds `chat_id` and `spotify_url` on `download_history`

## [0.7.0] - 2026-02-23

### Added

- Cancel-on-new-message: sending a new query while mid-search or mid-download
  cancels all in-flight operations for that chat instantly (generation counter
  + asyncio task cancellation)
- Large file OGG conversion: files >50 MB are converted to OGG Opus and sent
  in full; only trimmed to ~1 min if the OGG still exceeds 50 MB
- `convert_to_ogg()` utility (ffmpeg-based, handles any audio format)
- ffmpeg added as Docker system dependency for reliable audio conversion
- Dismiss-on-approve: saving one download to library automatically cancels all
  other pending downloads for the same chat (buttons removed, messages updated)
- `approval_message_id` tracking on `PendingDownload` for programmatic message edits

### Changed

- Results keyboard is now locked after selecting a download (no duplicate picks)
- Preview clips use ffmpeg → OGG Opus instead of soundfile (handles all formats)
- Default preview trim duration changed from 30 s to 60 s
- Stale approve/reject buttons now show "⏹ Cancelled" instead of silently
  disappearing

### Fixed

- "File too large for Telegram" text-only fallback no longer appears; files are
  always sent as playable audio (OGG conversion or trimmed clip)

## [0.4.0] - 2026-02-09

### Added

- FLAC authenticity analysis via spectral cutoff detection on downloaded files
  - Verdicts: AUTHENTIC, WARNING, SUSPICIOUS, FAKE shown before save approval
  - Uses Welch's PSD method to detect lossy-to-lossless transcodes
- Fallback to `send_document` when `send_audio` fails (BadRequest edge cases)
- New dependencies: numpy, scipy, soundfile for spectral analysis
- 9 new tests for FLAC analyzer (synthetic audio generation with controlled cutoffs)

### Changed

- Large file message improved with quality info and analysis results
- Download preview now shows FLAC authenticity verdict alongside quality info
- Dockerfile: added libsndfile1 system dependency for soundfile

## [0.3.5] - 2026-02-08

### Added

- Three-tier search fallback: full query -> title-only -> keyword reduction + album year
- Stale search cleanup before each new search (fixes slskd API caching bug)
- Configurable MAX_RESULTS environment variable for FLAC result display count

### Changed

- Default FLAC results display increased from 5 to 10

## [0.1.0] - 2026-02-07

### Added

- Initial release
- Telegram bot interface for song search and download
- Spotify metadata resolution (track name, artist, duration, album)
- slskd integration for FLAC search and download via Soulseek
- Scoring algorithm: duration matching, quality analysis, keyword filtering
- File processor: rename to "Artist - Title.flac" and place in output directory
- Auto-download mode (toggle with `/auto`)
- Download history and status commands
- FastAPI health check endpoint
- Docker support with security hardening
- GitHub Actions CI/CD (tests, lint, Docker publish, CodeQL, releases)

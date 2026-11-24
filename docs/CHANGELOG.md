# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — queue-first rework

- Every message is now a **batch in a download queue** with **one card** that updates in place. Send one song, twenty lines or a playlist link; several batches run side by side. The queue is persisted (schema v8: `queue_batches`, `queue_items`) and resumes after a restart
- `Artist - Title` is taken at its word: a catalog track is used only when it is that artist and title, so an underground song is no longer swapped for whatever the catalog returned first
- In a list, a copy is fetched unasked only when its remote path names the song (every title word, one artist word); otherwise the track waits for a pick
- After picking, skipping or retrying a track the card returns to where the track was opened from
- `/check` lists recently saved tracks whose name or source file does not match what was asked
- Every track now waits for its copy to be picked by hand; the unasked fetching of lists is behind `AUTO_PICK=true` (off by default). Only copies whose path names the song are offered; a track with none counts as not found and asks for nothing
- A saved copy the audio check does not vouch for (possible, likely or certain transcode) comes back to the main panel as ⚠️ with *Keep*, *Other copies* and *Undo*
- A copy you picked waits up to six hours in its peer's queue instead of failing after `DOWNLOAD_TIMEOUT_SECS` (which now only limits a transfer that is running)
- Failed tracks, like not-found ones, are counted and retried together but no longer listed one by one on the batch card
- A transfer waiting in a peer's upload queue no longer holds a queue slot, so busy peers cannot stall the other searches and downloads
- The copy you picked is stored with the track (schema v9), so a restart resumes the download instead of asking again
- A song sent on its own shows the copies found and waits for a pick; lists, playlists and tracklists run without asking
- **No confirmation step for lists.** The best lossless copy is fetched, spectrum-checked and saved. A fake FLAC is discarded and the next copy tried (three per track). Tracks with only lossy copies wait under *Choose a copy* instead of being saved silently
- Each track on a card can be opened: *Other copies*, *Undo*, *Send file*, *Retry*, *Download anyway* for songs already owned
- A copy stuck in a peer's upload queue for 90 seconds is dropped for the next copy instead of holding a queue slot for ten minutes (a copy you picked by hand still waits)
- The queue is fair across batches and limited to `MAX_CONCURRENT_DOWNLOADS` tracks at a time
- People without library access (`TELEGRAM_LIBRARY_USERS`) get every file sent to their chat; nothing of theirs is placed in the library
- `/status` lists the chat's batches; `/cancel` stops them all

### Added

- Sources beyond Spotify: YouTube / YouTube Music (videos, playlists, albums, DJ-mix chapters), SoundCloud, Bandcamp (via `yt-dlp`), 1001Tracklists pages, and pasted tracklists (numbering, timestamps and `[Label]` tags stripped). Non-Spotify entries are matched against the catalog when processed
- `/get` (alias `/import`) for people who prefer a command
- The already-owned check covers the whole collection (`LIBRARY_SWEEP_DIR`), not only the save folder: any file named `Artist - Title` in any subfolder counts, ignoring case, accents, punctuation, track numbers and an album in the middle
- `LIBRARY_SWEEP_DIR`: the sweep now walks a whole folder tree (default `OUTPUT_DIR`), so it can cover songs the bot did not save. A better copy replaces the song in its own folder. Changing the folder makes the next sweep measure every file again

### Removed

- The Spotify version picker, the per-download preview with Save/Discard approval, `APPROVAL_TTL_SECS`, and the separate playlist-import flow (`import_jobs` / `import_tracks` stay in the database, unused; unfinished imports are not carried over)

### Fixed

- A transfer slskd reports as `Completed, Errored` is treated as failed, not as a finished download whose file is missing (library sweep)
- The library sweep cancels a timed-out transfer by its full remote path, so slskd no longer keeps it
- History rows store the real saved file name (including a ` (1)` suffix), so undo removes the right file

## [Unreleased, before the queue rework]

### Added

- Import confirm card offers *Start and save everything*: tracks are saved to the library as they land, with no preview upload and no per-track Save tap (schema v7 adds `import_jobs.auto_save`; the choice survives restarts and `/import` resume)
- `Artist - Title` queries (also `–`, `—`, `|`) resolve with Spotify `artist:`/`track:` field filters before free text
- Pasted video titles are cleaned before lookup: `(Official Video)`, `[HD]`, `(Lyrics)`, trailing `official audio`, outer quotes

- Feedback through Telegram itself instead of extra messages: every button tap shows a toast ("Downloading…", "Saved", "Discarded"); your query message is reacted 👀 while searching, 🤷 when nothing turns up and 👍 once saved; "typing…" and "sending file…" chat actions during lookups and uploads
- The import progress message is pinned while the import runs and unpinned when it ends or is cancelled
- `/status` has a *Cancel all* button
- Bot description and short description (shown in the empty chat before `/start`) are set per locale on startup

### Changed

- Welcome text leads with what to send (two example queries, link types) and what the reactions mean, then the commands
- Soulseek result picks are a compact row of `#1 … #5` buttons under the list (the text already shows format, length, quality and size)
- No Spotify match now searches Soulseek directly at once, showing the parsed `Artist — Title` it will save as, instead of asking for another tap
- Spotify picker collapses the same recording across albums and reissues (same artist, title and length), so one real match goes straight to Soulseek
- Spotify picker buttons show length and year, and drop the artist when every candidate shares it
- Picking a version edits the picker into the search card instead of sending a second message
- Direct-search names keep typed casing (`AC/DC`, `McCartney`); only all-lowercase input is capitalized

### Removed

- Auto mode (`/auto`, `AUTO_MODE`). Results always show a pick keyboard; "Auto-pick best" remains a one-click `#1`

### Changed

- Python package renamed `music_downloader` → `slskd_importer` (`python -m slskd_importer`)
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
- i18n via in-code catalogs (no gettext/Babel): English (default), Spanish, Galician, and German. First `/start` shows a language picker; `/lang` (or `/language`) changes it later. Command menu descriptions are set per Telegram `language_code`
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

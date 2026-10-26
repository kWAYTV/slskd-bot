<h1 align="center">slskd-bot</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="License"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://github.com/kWAYTV/slskd-bot/pkgs/container/slskd-bot"><img src="https://img.shields.io/badge/ghcr.io-kwaytv%2Fslskd--bot-blue?logo=github" alt="GHCR"/></a>
</p>

<p align="center"><strong>Telegram bot that finds music on Soulseek. Send a song name or Spotify link, get a scored list of matches from <a href="https://github.com/slskd/slskd">slskd</a> (FLAC, WAV, AIFF, then the best available), and save the pick to your library as <code>Artist - Title</code>. Optionally sweeps the library for better copies and asks before replacing anything.</strong></p>

> This is a fork of [GeiserX/telegram-slskd-local-bot](https://github.com/GeiserX/telegram-slskd-local-bot), heavily reworked since. Credit for the original idea and foundation goes upstream.

## Features

- **Search by text or link** — free-text queries resolve via catalog metadata (Spotify today); pasted Spotify track links resolve directly, and playlist/album links start an import
- **Smart ranking** — prefers FLAC, then WAV, then AIFF, then the best remaining format; scored by duration, hi-res quality, source reliability, and filename relevance; live/remix noise filtered out
- **Languages** — English (default), Spanish, Galician, German. First `/start` picks a language; `/lang` changes it later
- **Playlist/album import** — `/import <url>` walks a whole Spotify playlist or album, skips tracks already in the library, and resumes after restart (`/import` with no URL continues an unfinished job)
- **Library sweep** — walks top-level library files, resolves artist/title from tags (or filename heuristics: track prefixes, `Artist - Album - Title`, rip brackets), looks on Soulseek for a better lossless copy, and sends side-by-side pairs in Telegram (`Keep mine` / `Take new` / `Keep both`). Never auto-replaces. Runs on a schedule or via `/sweep`
- **Live progress** — download messages update with a progress bar and queue state; `/status` shows everything in flight for the chat
- **Library hygiene** — canonical tags on save, duplicate detection, `/undo` / `/history` ↩️ to remove saves, `/stats` for totals
- **Large files** — files over Telegram's 50 MB limit fall back to OGG Opus previews, or upload untouched (up to 2000 MB) via a self-hosted Bot API server
- **Access control** — bot usage restricted to allowed user IDs; library writes (save, `/import`, `/sweep`) optionally restricted further via `TELEGRAM_LIBRARY_USERS`
- **Docker-ready** — image published to `ghcr.io/kwaytv/slskd-bot` on every push to `main`

## Quick Start

You need a running [slskd](https://github.com/slskd/slskd) instance with an API key, a free [Spotify Developer](https://developer.spotify.com/dashboard) app, and a Telegram bot token from [@BotFather](https://core.telegram.org/bots#botfather).

```yaml
services:
  slskd-bot:
    image: ghcr.io/kwaytv/slskd-bot:latest
    restart: unless-stopped
    environment:
      TELEGRAM_BOT_TOKEN: "your-bot-token"
      TELEGRAM_ALLOWED_USERS: "your-telegram-user-id"
      SPOTIFY_CLIENT_ID: "your-spotify-client-id"
      SPOTIFY_CLIENT_SECRET: "your-spotify-client-secret"
      SLSKD_HOST: "http://your-slskd-host:5030"
      SLSKD_API_KEY: "your-slskd-api-key"
    volumes:
      - /path/to/slskd/downloads:/downloads:ro
      - /path/to/music/library:/music
```

> With `/downloads` mounted read-only the bot cleans up originals through slskd's remote file management API — enable it with `SLSKD_REMOTE_FILE_MANAGEMENT=true` on the slskd side, or mount the volume read-write.

### Local development

```bash
git clone https://github.com/kWAYTV/slskd-bot.git && cd slskd-bot
uv sync
cp .env.example .env  # fill in credentials
uv run python -m slskd_importer run
```

## Commands

| Command | Description |
|---------|-------------|
| *(any text)* | Search for a song and show download options |
| *(Spotify track link)* | Resolve the link and search for it |
| *(Spotify playlist/album link)* | Start the import flow (library users only) |
| `/lang` | Change language (`/language` also works) |
| `/import <url>` | Import a Spotify playlist or album (library users only) |
| `/sweep` | Start a library sweep now (`/sweep force`, `/sweep status`, `/sweep reviews`) |
| `/undo` | Remove the last track saved to the library |
| `/status` | Active searches, downloads (with progress), and imports |
| `/history` | Recent downloads — tap ↩️ to remove one |
| `/stats` | Download totals and library size for this chat |
| `/cancel` | Cancel the current search, download, or import |

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USERS` | Yes | — | Comma-separated user IDs allowed to use the bot (empty denies everyone) |
| `TELEGRAM_LIBRARY_USERS` | No | — | User IDs allowed to save to the library, run `/import`, and get `/sweep` (empty = all allowed users) |
| `TELEGRAM_API_BASE_URL` | No | — | Self-hosted [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) URL; raises the upload limit to 2000 MB |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Yes | — | Spotify Developer app credentials |
| `SLSKD_HOST` | Yes | — | slskd instance URL |
| `SLSKD_API_KEY` | Yes | — | slskd API key (Settings > Security > API Keys) |
| `DOWNLOAD_DIR` | No | `/downloads` | Where slskd stores completed downloads |
| `OUTPUT_DIR` | No | `/music` | Where renamed files are placed (flat top-level audio files for the sweep) |
| `DATA_DIR` | No | `/data` | SQLite directory (history, imports, sweep) |
| `MAX_CONCURRENT_DOWNLOADS` | No | `3` | Cap on simultaneous slskd transfers |
| `APPROVAL_TTL_SECS` | No | `86400` | Discard unapproved downloads after this many seconds |
| `MAX_RESULTS` | No | `5` | Search results shown per query |
| `DURATION_TOLERANCE_SECS` | No | `5` | Duration match tolerance |
| `SEARCH_TIMEOUT_SECS` | No | `30` | slskd search timeout |
| `DOWNLOAD_TIMEOUT_SECS` | No | `600` | Download completion timeout |
| `EXCLUDE_KEYWORDS` | No | `live,remix,...` | Keywords filtered from results |
| `FILENAME_TEMPLATE` | No | `{artist} - {title}` | Output filename template |
| `LIBRARY_SWEEP_SCHEDULE` | No | `weekly:sun:04:00` | When the sweep starts on its own (`weekly:<mon..sun>:HH:MM`, `daily:HH:MM`, or `off`) |
| `LIBRARY_SWEEP_PAUSE_SECS` | No | `20` | Pause between songs that searched Soulseek |
| `LIBRARY_SWEEP_KEEP_DAYS` | No | `7` | Days a replaced original stays in `.sweep-replaced/` (`0` = purge at once, `never` = keep) |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `HEALTH_PORT` | No | `8080` | Health check HTTP port (`/health`, `/ready`) |

The sweep needs `ffmpeg` and the `analysis` extra (`numpy` / `scipy` / `soundfile`; already in the Docker image). Optional `fpcalc` (Chromaprint) improves the same-recording check; without it the sweep falls back to length and tags.

## License

[GPL-3.0](LICENSE) — same as the [original project](https://github.com/GeiserX/telegram-slskd-local-bot).

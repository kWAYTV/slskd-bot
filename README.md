<h1 align="center">slskd-bot</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="License"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://github.com/kWAYTV/slskd-bot/pkgs/container/slskd-bot"><img src="https://img.shields.io/badge/ghcr.io-kwaytv%2Fslskd--bot-blue?logo=github" alt="GHCR"/></a>
</p>

<p align="center"><strong>Telegram bot that gets music from Soulseek. Send song names, links or a whole tracklist; a download queue finds the best copy on <a href="https://github.com/slskd/slskd">slskd</a> (FLAC, WAV, AIFF first), checks it, and files it in your library as <code>Artist - Title</code>. One live card per message, nothing to confirm.</strong></p>

> This is a fork of [GeiserX/telegram-slskd-local-bot](https://github.com/GeiserX/telegram-slskd-local-bot), heavily reworked since. Credit for the original idea and foundation goes upstream.

## Features

- **Send anything, as much as you like** — one song per line, or links: Spotify (track, album, playlist), YouTube and YouTube Music (video, playlist, album, and the chapters of a DJ mix), SoundCloud, Bandcamp, 1001Tracklists, MixID and MixesDB pages. A tracklist copied from anywhere works too: numbering, timestamps and `[Label]` tags are stripped
- **One card per message** — every message becomes a batch with a single message that updates in place: progress, counts, what is downloading. Several batches run side by side without mixing. Your own message is reacted 👀 while it works, 👍 when something arrived, 🤷 when nothing did
- **Nothing to confirm** — the queue picks the best lossless copy, downloads it, runs a spectrum check, skips fake FLACs for the next copy, and saves. Only exceptions wait for you: no lossless copy exists (*Choose a copy*), nothing found, every copy failed
- **Every track stays in reach** — tap a track on its card to choose another copy, undo the save, get the file sent to the chat, or retry
- **Fair queue** — a fixed number of tracks at a time (`MAX_CONCURRENT_DOWNLOADS`), shared fairly: one song never waits behind a 300-track playlist. The queue survives restarts
- **Friends without touching your library** — people in `TELEGRAM_ALLOWED_USERS` but not in `TELEGRAM_LIBRARY_USERS` get their files sent to the chat (up to 2000 MB with a self-hosted Bot API server); nothing of theirs is ever saved to the library
- **Smart ranking** — FLAC, then WAV, then AIFF; scored by duration, hi-res quality, source reliability and filename; live/remix noise filtered out unless you asked for it
- **Library sweep** — walks the library (subfolders included; `LIBRARY_SWEEP_DIR` can point at your whole collection), looks on Soulseek for a better lossless copy of each song, and sends side-by-side pairs (`Keep mine` / `Take new` / `Keep both`). Never auto-replaces. Runs on a schedule or via `/sweep`
- **Library hygiene** — canonical tags and artwork on save, songs you already have anywhere in your collection are skipped (matched by `Artist - Title` file name; versions like `(Extended Mix)` are kept apart), `/undo` and `/history` ↩️ remove saves, `/stats` for totals
- **Languages** — English (default), Spanish, Galician, German. First `/start` picks a language; `/lang` changes it later
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

> Keep slskd's downloads folder **outside** the library folder. Files land there before they are checked; a media server or a sync tool watching the library would pick up unfinished and rejected downloads.

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
| *(any text)* | Queue the songs named, one per line |
| *(any link)* | Queue what the link holds: a track, an album, a playlist, a mix tracklist |
| `/status` | What this chat has in the queue, with *Cancel all* |
| `/history` | Recent downloads — tap ↩️ to remove one |
| `/undo` | Remove the last track saved to the library |
| `/stats` | Download totals and library size for this chat |
| `/sweep` | Start a library sweep now (`/sweep force`, `/sweep stop`, `/sweep status`, `/sweep reviews`) |
| `/lang` | Change language (`/language` also works) |
| `/cancel` | Stop everything this chat has in the queue |

`/get <text or link>` and `/import <link>` do the same as sending the text on its own.

### Source notes

- SoundCloud and Bandcamp are read track by track, so a long set takes a while to appear (about half a minute for 40 tracks).
- YouTube playlists give a title and a channel name, not a clean artist; label and compilation channels can produce wrong guesses. The catalog lookup fixes most of them.
- MixID sits behind a browser check that refuses bots, so a MixID link normally answers "paste it as text". Copy the tracklist from the page and send it; that works.
- 1001Tracklists may block automated requests. The bot then says so; copy the tracklist and paste it.
- Source error messages are in English in every language.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USERS` | Yes | — | Comma-separated user IDs allowed to use the bot (empty denies everyone) |
| `TELEGRAM_LIBRARY_USERS` | No | — | User IDs whose downloads are saved to the library and who get `/sweep` and `/undo`. Other allowed users get files sent to their chat (empty = all allowed users save) |
| `TELEGRAM_API_BASE_URL` | No | — | Self-hosted [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) URL; raises the upload limit to 2000 MB |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Yes | — | Spotify Developer app credentials |
| `SLSKD_HOST` | Yes | — | slskd instance URL |
| `SLSKD_API_KEY` | Yes | — | slskd API key (Settings > Security > API Keys) |
| `DOWNLOAD_DIR` | No | `/downloads` | Where slskd stores completed downloads (keep it outside the library) |
| `OUTPUT_DIR` | No | `/music` | Where renamed files are placed |
| `DATA_DIR` | No | `/data` | SQLite directory (queue, history, sweep) |
| `MAX_CONCURRENT_DOWNLOADS` | No | `3` | Tracks the queue works on at the same time |
| `MAX_RESULTS` | No | `5` | Copies shown per page when choosing one by hand |
| `DURATION_TOLERANCE_SECS` | No | `5` | Duration match tolerance |
| `SEARCH_TIMEOUT_SECS` | No | `30` | slskd search timeout |
| `DOWNLOAD_TIMEOUT_SECS` | No | `600` | Download completion timeout |
| `EXCLUDE_KEYWORDS` | No | `live,remix,...` | Keywords filtered from results |
| `FILENAME_TEMPLATE` | No | `{artist} - {title}` | Output filename template |
| `LIBRARY_SWEEP_DIR` | No | `OUTPUT_DIR` | Root of your collection: the sweep walks it (subfolders included), and a song found anywhere under it by its `Artist - Title` file name is not downloaded again. Hidden folders are skipped |
| `LIBRARY_SWEEP_SCHEDULE` | No | `weekly:sun:04:00` | When the sweep starts on its own (`weekly:<mon..sun>:HH:MM`, `daily:HH:MM`, or `off`) |
| `LIBRARY_SWEEP_PAUSE_SECS` | No | `20` | Pause between songs that searched Soulseek |
| `LIBRARY_SWEEP_KEEP_DAYS` | No | `7` | Days a replaced original stays in `.sweep-replaced/` (`0` = purge at once, `never` = keep) |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `HEALTH_PORT` | No | `8080` | Health check HTTP port (`/health`, `/ready`) |

The sweep needs `ffmpeg` and the `analysis` extra (`numpy` / `scipy` / `soundfile`; already in the Docker image). Optional `fpcalc` (Chromaprint) improves the same-recording check; without it the sweep falls back to length and tags.

## License

[GPL-3.0](LICENSE) — same as the [original project](https://github.com/GeiserX/telegram-slskd-local-bot).

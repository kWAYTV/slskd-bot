<h1 align="center">slskd-bot</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="License"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://github.com/kWAYTV/slskd-bot/pkgs/container/slskd-bot"><img src="https://img.shields.io/badge/ghcr.io-kwaytv%2Fslskd--bot-blue?logo=github" alt="GHCR"/></a>
</p>

<p align="center"><strong>Telegram bot that finds music on Soulseek. Send a song name or Spotify link, get a scored list of FLAC matches from <a href="https://github.com/slskd/slskd">slskd</a>, and save the best one to your library as <code>Artist - Title.flac</code>.</strong></p>

> This is a fork of [GeiserX/telegram-slskd-local-bot](https://github.com/GeiserX/telegram-slskd-local-bot), heavily reworked since. Credit for the original idea and foundation goes upstream.

## Features

- **Search by text or link** — free-text queries resolve via Spotify metadata; pasted Spotify track links resolve directly, and playlist/album links start an import
- **Smart ranking** — results scored by duration match, audio quality, source reliability, and filename relevance; live/remix noise filtered out
- **Quality preference** — `/quality` picks CD (16/44.1) or Hi-Res (24-bit) ranking per chat
- **Auto mode** — `/auto` per chat downloads the best match without asking
- **Playlist/album import** — `/import <url>` walks a whole Spotify playlist or album, with progress, per-track retry/skip, and resume after restart
- **Live progress** — download messages update with a progress bar; `/status` shows everything in flight for the chat
- **Library hygiene** — duplicate detection before searching, `/undo` to remove the last save, `/history` per chat
- **Large files** — files over Telegram's 50 MB limit fall back to OGG Opus previews, or upload untouched (up to 2000 MB) via a self-hosted Bot API server
- **Access control** — bot usage restricted to allowed user IDs; library writes optionally restricted further via `TELEGRAM_LIBRARY_USERS`
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
uv run python -m music_downloader run
```

## Commands

| Command | Description |
|---------|-------------|
| *(any text)* | Search for a song and show download options |
| *(Spotify track link)* | Resolve the link and search for it |
| *(Spotify playlist/album link)* | Start the import flow (library users only) |
| `/auto` | Toggle auto-download of the best match (per chat) |
| `/quality` | Prefer CD or Hi-Res when ranking results (per chat) |
| `/import <url>` | Import a Spotify playlist or album (library users only) |
| `/import resume` | Continue a paused import after a restart |
| `/undo` | Remove the last track saved to the library |
| `/status` | Active searches, downloads (with progress), and imports |
| `/history` | Recent download history for this chat |
| `/cancel` | Cancel the current search, download, or import |

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USERS` | Yes | — | Comma-separated user IDs allowed to use the bot (empty denies everyone) |
| `TELEGRAM_LIBRARY_USERS` | No | — | User IDs allowed to save to the library and run `/import` (empty = all allowed users) |
| `TELEGRAM_API_BASE_URL` | No | — | Self-hosted [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) URL; raises the upload limit to 2000 MB |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Yes | — | Spotify Developer app credentials |
| `SLSKD_HOST` | Yes | — | slskd instance URL |
| `SLSKD_API_KEY` | Yes | — | slskd API key (Settings > Security > API Keys) |
| `DOWNLOAD_DIR` | No | `/downloads` | Where slskd stores completed downloads |
| `OUTPUT_DIR` | No | `/music` | Where renamed files are placed |
| `DATA_DIR` | No | `/data` | SQLite directory (history, imports) |
| `AUTO_MODE` | No | `false` | Default for the per-chat `/auto` toggle |
| `QUALITY_PREFERENCE` | No | `hires` | Default for the per-chat `/quality` toggle (`hires` or `cd`) |
| `MAX_RESULTS` | No | `5` | Search results shown per query |
| `DURATION_TOLERANCE_SECS` | No | `5` | Duration match tolerance |
| `SEARCH_TIMEOUT_SECS` | No | `30` | slskd search timeout |
| `DOWNLOAD_TIMEOUT_SECS` | No | `600` | Download completion timeout |
| `EXCLUDE_KEYWORDS` | No | `live,remix,...` | Keywords filtered from results |
| `FILENAME_TEMPLATE` | No | `{artist} - {title}` | Output filename template |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `HEALTH_PORT` | No | `8080` | Health check HTTP port (`/health`, `/ready`) |

## License

[GPL-3.0](LICENSE) — same as the [original project](https://github.com/GeiserX/telegram-slskd-local-bot).

# Anime Cloud Music Pro

Production-oriented Python Discord music extension for merging into the Anime Cloud bot.

## Features
- Slash commands: `/play`, `/queue`, `/nowplaying`, `/skip`, `/remove`, `/clear`, `/pause`, `/resume`, `/stop`, `/disconnect`, `/volume`, `/shuffle`, `/loop`, `/autoplay`, `/filter`
- Persistent per-guild playlists
- Interactive playback control buttons
- YouTube search/URL support through yt-dlp
- FFmpeg reconnect support and audio filters

## Installation
```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python bot.py
```

## Environment
`DISCORD_TOKEN` is required. `GUILD_ID` is optional for fast command syncing.

> Merge note: keep only one `bot.run()` in the main Anime Cloud entrypoint.

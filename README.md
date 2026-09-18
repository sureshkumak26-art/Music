# Anime Cloud Music Pro

Professional Python Discord music bot for Anime Cloud.

## Features
- Slash commands: `/play`, `/queue`, `/nowplaying`, `/pause`, `/resume`, `/skip`, `/stop`, `/clear`, `/remove`, `/disconnect`
- Queue controls, shuffle, loop, autoplay, volume and audio filters
- Persistent per-server playlists: `/playlist_save`, `/playlist_load`, `/playlist_list`, `/playlist_delete`
- Interactive control buttons
- YouTube search and URL playback through yt-dlp + FFmpeg
- Reconnect-safe FFmpeg streaming and structured logging
- Optional **24/7 voice mode** through `voice24.py`

## Install (Ubuntu 22.04/24.04)
```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg git
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python bot.py
```

## Environment
```env
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_server_id
LOG_LEVEL=INFO

VOICE_CHANNEL_ID=your_voice_channel_id
AUTO_JOIN_VC=true
KEEP_ALIVE=true
```

## Enable 24/7 voice mode
`voice24.py` is a drop-in reconnect manager. Import it in the same process as your existing bot; do not create a second Discord login.

```python
from voice24 import Voice24Manager

voice24 = Voice24Manager(bot, on_reconnect=on_voice_reconnect)

@bot.event
async def on_ready():
    await voice24.start()
```

For autoplay integration, define `on_voice_reconnect(guild)` to call your existing guild playback/queue function when appropriate. Keep exactly one `bot.run()` call.

Enable the bot's **Connect**, **Speak**, **View Channel**, and **Send Messages** permissions. Keep the token private.

## Merge into Anime Cloud
This repository is designed to be merged into an existing Python Discord bot. Import the music classes/commands into your main bot and keep exactly one `bot.run()` call. Do not run two bot processes using the same token.

## Production notes
Use systemd or a process manager, keep `data/` persistent, and update `yt-dlp` regularly. The included implementation uses FFmpeg streaming; for large multi-server deployments, move playback to Lavalink/Wavelink.

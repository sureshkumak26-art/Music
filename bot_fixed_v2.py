"""Anime Cloud Music Bot v2
Created by Mrhacker.
Fixes YouTube search timeout, safe interaction replies, and 24/7 VC mode.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("anime-cloud-music")

YTDL_OPTIONS = {
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "socket_timeout": 20,
    "retries": 3,
    "fragment_retries": 3,
    "skip_unavailable_fragments": True,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

@dataclass
class Track:
    title: str
    webpage: str
    stream: str
    requester: str

@dataclass
class State:
    queue: list[Track] = field(default_factory=list)
    current: Optional[Track] = None
    voice: Optional[discord.VoiceClient] = None
    text_channel: Optional[discord.abc.Messageable] = None
    autoplay: bool = True
    nonstop: bool = False
    target_channel_id: Optional[int] = None
    volume: int = 70
    started_at: float = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

states: dict[int, State] = {}
nonstop_tasks: dict[int, asyncio.Task] = {}

def state_for(guild_id: int) -> State:
    return states.setdefault(guild_id, State())

async def resolve_track(query: str, requester: str) -> Track:
    def extract() -> Track:
        search = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(search, download=False)
            if info.get("entries"):
                info = next((item for item in info["entries"] if item), None)
            if not info or not info.get("url"):
                raise RuntimeError("No playable audio stream was found.")
            return Track(
                title=info.get("title", "Unknown"),
                webpage=info.get("webpage_url", query),
                stream=info["url"],
                requester=requester,
            )

    return await asyncio.wait_for(asyncio.to_thread(extract), timeout=90)

def source_for(track: Track, st: State):
    return discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(track.stream, **FFMPEG_OPTIONS),
        volume=st.volume / 100,
    )

async def send_text(st: State, message: str):
    if st.text_channel:
        try:
            await st.text_channel.send(message)
        except discord.HTTPException:
            pass

async def play_next(guild: discord.Guild):
    st = state_for(guild.id)
    async with st.lock:
        if not st.voice or not st.voice.is_connected():
            return
        if st.queue:
            track = st.queue.pop(0)
        elif st.autoplay and st.current:
            try:
                track = await resolve_track(st.current.title, "Autoplay")
            except Exception as exc:
                log.warning("Autoplay failed: %s", exc)
                st.current = None
                return
        else:
            st.current = None
            await send_text(st, "Queue finished. Use `/play` to add music.")
            return

        st.current = track
        st.started_at = time.time()

        def after(error):
            if error:
                log.warning("Playback error: %s", error)
            asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

        st.voice.play(source_for(track, st), after=after)
        await send_text(st, f"▶️ **{track.title}** — requested by `{track.requester}`")

async def ensure_voice(guild: discord.Guild, channel: discord.VoiceChannel) -> State:
    st = state_for(guild.id)
    if st.voice and st.voice.is_connected():
        if st.voice.channel.id != channel.id:
            await st.voice.move_to(channel)
    else:
        st.voice = await channel.connect(timeout=30, reconnect=True)
    st.target_channel_id = channel.id
    return st

async def nonstop_loop(guild: discord.Guild):
    st = state_for(guild.id)
    while st.nonstop:
        try:
            channel = guild.get_channel(st.target_channel_id) if st.target_channel_id else None
            if isinstance(channel, discord.VoiceChannel):
                if not st.voice or not st.voice.is_connected():
                    st.voice = await channel.connect(timeout=30, reconnect=True)
                elif st.voice.channel.id != channel.id:
                    await st.voice.move_to(channel)
                if not st.voice.is_playing() and not st.voice.is_paused() and (st.queue or st.current):
                    await play_next(guild)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("24/7 reconnect check failed: %s", exc)
        await asyncio.sleep(10)

class MusicBot(commands.Bot):
    async def setup_hook(self):
        if GUILD_ID and GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
bot = MusicBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="Created by Mrhacker 🎵",
        ),
    )
    log.info("Logged in as %s | Created by Mrhacker", bot.user)

@bot.tree.command(name="play", description="Play a song or YouTube URL")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    if not interaction.guild or not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ Join a voice channel first.", ephemeral=True)
        return
    try:
        st = await ensure_voice(interaction.guild, interaction.user.voice.channel)
        st.text_channel = interaction.channel
        track = await resolve_track(query, str(interaction.user))
        st.queue.append(track)
        await interaction.followup.send(f"➕ Added **{track.title}**")
        if not st.voice.is_playing() and not st.voice.is_paused():
            await play_next(interaction.guild)
    except asyncio.TimeoutError:
        await interaction.followup.send(
            "❌ YouTube timed out after 90 seconds. Update yt-dlp and try a direct YouTube URL.",
            ephemeral=True,
        )
    except Exception as exc:
        log.exception("Play command failed")
        await interaction.followup.send(
            f"❌ Could not load audio: `{type(exc).__name__}`. Check the VPS network and yt-dlp version.",
            ephemeral=True,
        )

@bot.tree.command(name="247", description="Enable or disable nonstop voice mode")
@app_commands.describe(action="Turn 24/7 voice mode on or off")
@app_commands.choices(action=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def voice_247(interaction: discord.Interaction, action: app_commands.Choice[str]):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    st = state_for(interaction.guild_id)
    if action.value == "off":
        st.nonstop = False
        task = nonstop_tasks.pop(interaction.guild_id, None)
        if task:
            task.cancel()
        if st.voice and st.voice.is_connected():
            await st.voice.disconnect(force=True)
        st.voice = None
        await interaction.response.send_message("🛑 24/7 mode disabled.\nCreated by **Mrhacker**.")
        return

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("Join the voice channel first.", ephemeral=True)
        return
    try:
        st = await ensure_voice(interaction.guild, interaction.user.voice.channel)
        st.text_channel = interaction.channel
        st.nonstop = True
        st.autoplay = True
        task = nonstop_tasks.get(interaction.guild_id)
        if not task or task.done():
            nonstop_tasks[interaction.guild_id] = asyncio.create_task(nonstop_loop(interaction.guild))
        await interaction.response.send_message(
            "🔁 24/7 mode enabled. Autoplay and reconnect are active.\nCreated by **Mrhacker**."
        )
    except Exception as exc:
        log.exception("24/7 enable failed")
        await interaction.response.send_message(
            f"❌ Could not join voice: `{type(exc).__name__}`",
            ephemeral=True,
        )

@bot.tree.command(name="queue", description="Show the current queue")
async def queue(interaction: discord.Interaction):
    st = state_for(interaction.guild_id)
    lines = [f"**Now:** {st.current.title if st.current else 'Nothing'}"]
    lines.extend(f"`{idx}` {track.title}" for idx, track in enumerate(st.queue, 1))
    await interaction.response.send_message("🎶 **Anime Cloud Queue**\n" + "\n".join(lines[:26]))

@bot.tree.command(name="stop", description="Stop playback and clear queue")
async def stop(interaction: discord.Interaction):
    st = state_for(interaction.guild_id)
    st.queue.clear()
    st.current = None
    if st.voice and st.voice.is_playing():
        st.voice.stop()
    await interaction.response.send_message("⏹️ Playback stopped and queue cleared.")

@bot.tree.command(name="disconnect", description="Disconnect from voice")
async def disconnect(interaction: discord.Interaction):
    st = state_for(interaction.guild_id)
    st.nonstop = False
    task = nonstop_tasks.pop(interaction.guild_id, None)
    if task:
        task.cancel()
    if st.voice and st.voice.is_connected():
        await st.voice.disconnect(force=True)
    st.voice = None
    await interaction.response.send_message("Disconnected from voice.")

bot.run(TOKEN)

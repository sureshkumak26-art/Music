"""Anime Cloud Lavalink Music Bot
Created by Mrhacker.

Requires Lavalink v4 running separately and Wavelink 3.x.
"""

import asyncio
import logging
import os
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import wavelink

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("anime-cloud-lavalink")

queues: dict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
nonstop: set[int] = set()
target_channels: dict[int, int] = {}
text_channels: dict[int, discord.abc.Messageable] = {}


class AnimeCloudBot(commands.Bot):
    async def setup_hook(self) -> None:
        node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
        await wavelink.Pool.connect(nodes=[node], client=self, cache_capacity=100)
        if GUILD_ID and GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
bot = AnimeCloudBot(command_prefix="!", intents=intents)


async def send_guild_message(guild_id: int, message: str) -> None:
    channel = text_channels.get(guild_id)
    if channel:
        try:
            await channel.send(message)
        except discord.HTTPException:
            pass


async def get_player(interaction: discord.Interaction) -> wavelink.Player | None:
    if not interaction.guild:
        return None
    voice = interaction.guild.voice_client
    return voice if isinstance(voice, wavelink.Player) else None


async def ensure_player(interaction: discord.Interaction) -> wavelink.Player:
    if not interaction.guild or not interaction.user.voice or not interaction.user.voice.channel:
        raise RuntimeError("Join a voice channel first.")

    channel = interaction.user.voice.channel
    player = await get_player(interaction)
    if player and player.is_connected():
        if player.channel.id != channel.id:
            await player.move_to(channel)
    else:
        player = await channel.connect(cls=wavelink.Player)

    target_channels[interaction.guild.id] = channel.id
    text_channels[interaction.guild.id] = interaction.channel
    return player


async def play_next(guild: discord.Guild, player: wavelink.Player) -> None:
    guild_id = guild.id
    if player.playing:
        return
    try:
        track = queues[guild_id].get_nowait()
    except asyncio.QueueEmpty:
        return
    await player.play(track)
    await send_guild_message(guild_id, f"▶️ **{track.title}**\nCreated by **Mrhacker**")


@bot.event
async def on_ready() -> None:
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.listening, name="Created by Mrhacker 🎵"),
    )
    log.info("Logged in as %s | Lavalink mode | Created by Mrhacker", bot.user)


@bot.listen("on_wavelink_track_end")
async def on_track_end(payload: wavelink.TrackEndEventPayload) -> None:
    player = payload.player
    guild = player.guild
    if not guild:
        return
    if guild.id in nonstop:
        try:
            if player.current:
                related = await wavelink.Playable.search(player.current.title)
                if related:
                    await player.play(related[0])
                    return
        except Exception as exc:
            log.warning("Autoplay failed: %s", exc)
    await play_next(guild, player)


@bot.listen("on_wavelink_node_ready")
async def on_node_ready(payload: wavelink.NodeReadyEventPayload) -> None:
    log.info("Lavalink node ready: %s", payload.node.identifier)


@bot.tree.command(name="play", description="Play a song using Lavalink")
@app_commands.describe(query="YouTube URL or search text")
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        player = await ensure_player(interaction)
        results = await wavelink.Playable.search(query)
        if not results:
            await interaction.followup.send("❌ No playable results found.", ephemeral=True)
            return
        track = results[0]
        await queues[interaction.guild.id].put(track)
        if not player.playing:
            await play_next(interaction.guild, player)
        await interaction.followup.send(f"➕ Added **{track.title}**")
    except Exception as exc:
        log.exception("Lavalink play failed")
        await interaction.followup.send(f"❌ Lavalink error: `{type(exc).__name__}: {exc}`", ephemeral=True)


@bot.tree.command(name="247", description="Enable or disable nonstop voice mode")
@app_commands.describe(action="Turn 24/7 voice mode on or off")
@app_commands.choices(action=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
async def voice_247(interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Server only.", ephemeral=True)
        return
    guild_id = interaction.guild.id
    if action.value == "off":
        nonstop.discard(guild_id)
        player = await get_player(interaction)
        if player:
            await player.disconnect()
        await interaction.response.send_message("🛑 24/7 mode disabled.\nCreated by **Mrhacker**.")
        return

    try:
        player = await ensure_player(interaction)
        nonstop.add(guild_id)
        await interaction.response.send_message("🔁 24/7 mode enabled: reconnect/autoplay mode is active.\nCreated by **Mrhacker**.")
        if not player.playing:
            await play_next(interaction.guild, player)
    except Exception as exc:
        await interaction.response.send_message(f"❌ Could not enable 24/7: `{type(exc).__name__}: {exc}`", ephemeral=True)


@bot.tree.command(name="stop", description="Stop playback")
async def stop(interaction: discord.Interaction) -> None:
    player = await get_player(interaction)
    if player:
        await player.stop()
    queues[interaction.guild.id] = asyncio.Queue()
    await interaction.response.send_message("⏹️ Playback stopped.")


@bot.tree.command(name="disconnect", description="Disconnect from voice")
async def disconnect(interaction: discord.Interaction) -> None:
    nonstop.discard(interaction.guild.id)
    player = await get_player(interaction)
    if player:
        await player.disconnect()
    await interaction.response.send_message("👋 Disconnected.")


bot.run(TOKEN)

"""Anime Cloud Music Bot - 24/7 Voice Mode
Created by Mrhacker

Load this extension from bot.py with:
    await bot.load_extension("voice247")
"""
import asyncio
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

CONFIG_PATH = Path("data/voice247.json")
CONFIG_PATH.parent.mkdir(exist_ok=True)


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


class Voice247(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tasks = {}
        self.config = load_config()

    def get_state(self, guild_id):
        return self.bot.get_state(guild_id) if hasattr(self.bot, "get_state") else None

    async def keep_connected(self, guild_id):
        while self.config.get(str(guild_id), {}).get("enabled", False):
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel_id = self.config[str(guild_id)].get("channel_id")
                channel = guild.get_channel(channel_id) if channel_id else None
                state = self.get_state(guild_id)
                try:
                    if channel and state:
                        if not state.voice or not state.voice.is_connected():
                            state.voice = await channel.connect()
                        elif state.voice.channel.id != channel.id:
                            await state.voice.move_to(channel)
                        if not state.voice.is_playing() and not state.voice.is_paused():
                            advance = getattr(self.bot, "advance", None)
                            if advance:
                                await advance(guild)
                except (discord.DiscordException, asyncio.CancelledError):
                    pass
            await asyncio.sleep(10)

    @app_commands.command(name="247", description="Enable or disable nonstop voice mode")
    @app_commands.choices(action=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def voice_247(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if action.value == "off":
            self.config[str(interaction.guild_id)] = {"enabled": False}
            save_config(self.config)
            task = self.tasks.pop(interaction.guild_id, None)
            if task:
                task.cancel()
            state = self.get_state(interaction.guild_id)
            if state and state.voice:
                await state.voice.disconnect(force=True)
                state.voice = None
            await interaction.response.send_message("🔴 **24/7 mode disabled.** Disconnected.\n*Created by Mrhacker*")
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        self.config[str(interaction.guild_id)] = {
            "enabled": True,
            "channel_id": channel.id,
        }
        save_config(self.config)

        old_task = self.tasks.get(interaction.guild_id)
        if old_task and not old_task.done():
            old_task.cancel()
        self.tasks[interaction.guild_id] = asyncio.create_task(self.keep_connected(interaction.guild_id))

        await interaction.response.send_message(
            f"🟢 **24/7 mode enabled!**\n"
            f"Connected channel: **{channel.name}**\n"
            f"Autoplay + automatic reconnect enabled.\n"
            f"*Created by Mrhacker*"
        )


async def setup(bot):
    await bot.add_cog(Voice247(bot))

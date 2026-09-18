"""Anime Cloud 24/7 voice helper.

Usage from bot.py (after bot is created):
    from voice24 import Voice24Manager
    voice24 = Voice24Manager(bot)
    # In on_ready: await voice24.start()

Environment:
    VOICE_CHANNEL_ID=123456789012345678
    AUTO_JOIN_VC=true
    KEEP_ALIVE=true

The helper reconnects to the configured voice channel and can optionally
start playback through the existing guild State/advance functions.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Optional

import discord

log = logging.getLogger("anime-cloud-voice24")


class Voice24Manager:
    def __init__(
        self,
        bot: discord.Client,
        on_reconnect: Optional[Callable[[discord.Guild], Awaitable[None]]] = None,
    ) -> None:
        self.bot = bot
        self.channel_id = int(os.getenv("VOICE_CHANNEL_ID", "0") or 0)
        self.enabled = os.getenv("AUTO_JOIN_VC", "false").lower() in {"1", "true", "yes", "on"}
        self.keep_alive = os.getenv("KEEP_ALIVE", "true").lower() in {"1", "true", "yes", "on"}
        self.on_reconnect = on_reconnect
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if not self.enabled or not self.channel_id or self._task:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._watch(), name="anime-cloud-voice24")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def _watch(self) -> None:
        await self.bot.wait_until_ready()
        while not self._stopping:
            try:
                channel = self.bot.get_channel(self.channel_id)
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    log.warning("VOICE_CHANNEL_ID is invalid or not cached: %s", self.channel_id)
                else:
                    voice = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
                    if voice and voice.is_connected():
                        if voice.channel.id != channel.id:
                            await voice.move_to(channel)
                    else:
                        voice = await channel.connect(reconnect=True, timeout=30)
                        log.info("Connected to 24/7 voice channel: %s", channel.name)
                        if self.on_reconnect:
                            await self.on_reconnect(channel.guild)
                await asyncio.sleep(20 if self.keep_alive else 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("24/7 voice watcher error; retrying")
                await asyncio.sleep(10)

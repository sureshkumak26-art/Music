"""Anime Cloud Music Pro - single-file Discord.py music bot.
Features: queue, autoplay, playlists, buttons, filters, loop, volume.
"""
import asyncio, json, logging, os, random, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
if not TOKEN: raise RuntimeError("Missing DISCORD_TOKEN in .env")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("anime-cloud-music")
DATA = Path("data"); DATA.mkdir(exist_ok=True)
PLAYLISTS = DATA / "playlists.json"
FILTERS = {"clear":"", "nightcore":"asetrate=48000*1.25,aresample=48000,atempo=1.0", "bassboost":"equalizer=f=100:t=q:w=1:g=8", "8d":"apulsator=hz=0.08", "vaporwave":"asetrate=48000*0.8,aresample=48000,atempo=1.25"}
YTDL = {"format":"bestaudio/best", "noplaylist":True, "quiet":True, "default_search":"ytsearch1"}
FFMPEG = {"before_options":"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", "options":"-vn"}

@dataclass
class Track:
    title: str; webpage: str; stream: str; requester: str
@dataclass
class State:
    queue: list[Track] = field(default_factory=list)
    current: Optional[Track] = None
    voice: Optional[discord.VoiceClient] = None
    channel: Optional[discord.abc.Messageable] = None
    volume: int = 70; loop: bool = False; autoplay: bool = True; filter_name: str = "clear"
    started: float = 0; lock: asyncio.Lock = field(default_factory=asyncio.Lock)
states: dict[int, State] = {}
def get_state(gid): return states.setdefault(gid, State())

def load_data():
    try: return json.loads(PLAYLISTS.read_text())
    except Exception: return {}
def save_data(data): PLAYLISTS.write_text(json.dumps(data, indent=2))

async def resolve(query, requester):
    def work():
        with yt_dlp.YoutubeDL(YTDL) as ydl:
            info = ydl.extract_info(query if query.startswith("http") else f"ytsearch1:{query}", download=False)
            if info.get("entries"): info = next(x for x in info["entries"] if x)
            return Track(info.get("title", "Unknown"), info.get("webpage_url", query), info["url"], requester)
    return await asyncio.to_thread(work)

def make_source(track, st):
    opts = dict(FFMPEG); filt = FILTERS.get(st.filter_name, "")
    if filt: opts["options"] += f' -af "{filt}"'
    return discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(track.stream, **opts), volume=st.volume/100)

async def announce(st, text):
    if st.channel:
        try: await st.channel.send(text)
        except discord.HTTPException: pass
async def advance(guild):
    st = get_state(guild.id)
    async with st.lock:
        if not st.voice or not st.voice.is_connected(): return
        if st.loop and st.current: track = st.current
        elif st.queue: track = st.queue.pop(0)
        elif st.autoplay and st.current:
            try: track = await resolve(st.current.title, "Autoplay")
            except Exception as exc: log.warning("Autoplay failed: %s", exc); st.current = None; return
        else: st.current = None; await announce(st, "Queue finished."); return
        st.current = track; st.started = time.time()
        def after(error):
            if error: log.warning("Playback error: %s", error)
            asyncio.run_coroutine_threadsafe(advance(guild), bot.loop)
        st.voice.play(make_source(track, st), after=after)
        await announce(st, f"▶️ **{track.title}** — `{track.requester}`")

class Controls(discord.ui.View):
    def __init__(self, gid): super().__init__(timeout=900); self.gid = gid
    async def interaction_check(self, i):
        if not i.user.voice: await i.response.send_message("Join a voice channel first.", ephemeral=True); return False
        return True
    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause(self, i, _):
        st=get_state(self.gid)
        if st.voice and st.voice.is_playing(): st.voice.pause(); await i.response.send_message("Paused.", ephemeral=True)
        else: await i.response.send_message("Nothing is playing.", ephemeral=True)
    @discord.ui.button(label="Resume", emoji="▶️", style=discord.ButtonStyle.success)
    async def resume(self, i, _):
        st=get_state(self.gid)
        if st.voice and st.voice.is_paused(): st.voice.resume(); await i.response.send_message("Resumed.", ephemeral=True)
        else: await i.response.send_message("Nothing is paused.", ephemeral=True)
    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip(self, i, _):
        st=get_state(self.gid)
        if st.voice and st.voice.is_playing(): st.voice.stop(); await i.response.send_message("Skipped.", ephemeral=True)
        else: await i.response.send_message("Nothing is playing.", ephemeral=True)
    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, i, _):
        st=get_state(self.gid); st.queue.clear(); st.current=None
        if st.voice: st.voice.stop()
        await i.response.send_message("Stopped and queue cleared.", ephemeral=True)

class MusicBot(commands.Bot):
    async def setup_hook(self):
        if GUILD_ID and GUILD_ID.isdigit():
            guild=discord.Object(int(GUILD_ID)); self.tree.copy_global_to(guild=guild); await self.tree.sync(guild=guild)
        else: await self.tree.sync()
intents=discord.Intents.default(); intents.guilds=True; intents.voice_states=True
bot=MusicBot(command_prefix="!", intents=intents)

async def connect_voice(i):
    if not i.user.voice or not i.user.voice.channel: await i.followup.send("Join a voice channel first.", ephemeral=True); return None
    st=get_state(i.guild_id); ch=i.user.voice.channel
    if st.voice and st.voice.is_connected():
        if st.voice.channel != ch: await st.voice.move_to(ch)
    else: st.voice=await ch.connect()
    st.channel=i.channel; return st

@bot.event
async def on_ready(): log.info("Logged in as %s", bot.user)

@bot.tree.command(name="play", description="Play a song or URL")
async def play(i: discord.Interaction, query: str):
    await i.response.defer(); st=await connect_voice(i)
    if not st: return
    try:
        t=await resolve(query, str(i.user)); st.queue.append(t)
        await i.followup.send(f"➕ Added **{t.title}**", view=Controls(i.guild_id))
        if not st.voice.is_playing() and not st.voice.is_paused(): await advance(i.guild)
    except Exception as exc: log.exception("Resolve failed"); await i.followup.send(f"Could not load track: `{exc}`", ephemeral=True)

@bot.tree.command(name="queue", description="Show queue")
async def queue(i):
    st=get_state(i.guild_id); lines=[f"**Now:** {st.current.title if st.current else 'Nothing'}"]+[f"`{n}` {t.title}" for n,t in enumerate(st.queue,1)]
    await i.response.send_message("🎶 **Anime Cloud Queue**\n"+"\n".join(lines[:26]))

@bot.tree.command(name="nowplaying", description="Show current track")
async def nowplaying(i):
    st=get_state(i.guild_id)
    if not st.current: return await i.response.send_message("Nothing is playing.", ephemeral=True)
    e=int(time.time()-st.started) if st.started else 0
    em=discord.Embed(title="🎵 Now Playing", description=f"[{st.current.title}]({st.current.webpage})", color=discord.Color.blurple())
    em.add_field(name="Elapsed", value=f"{e}s").add_field(name="Volume", value=f"{st.volume}%").add_field(name="Filter", value=st.filter_name)
    await i.response.send_message(embed=em, view=Controls(i.guild_id))

@bot.tree.command(name="pause", description="Pause")
async def pause(i):
    st=get_state(i.guild_id)
    if st.voice and st.voice.is_playing(): st.voice.pause(); await i.response.send_message("Paused.")
    else: await i.response.send_message("Nothing is playing.", ephemeral=True)
@bot.tree.command(name="resume", description="Resume")
async def resume(i):
    st=get_state(i.guild_id)
    if st.voice and st.voice.is_paused(): st.voice.resume(); await i.response.send_message("Resumed.")
    else: await i.response.send_message("Nothing is paused.", ephemeral=True)
@bot.tree.command(name="skip", description="Skip")
async def skip(i):
    st=get_state(i.guild_id)
    if st.voice and st.voice.is_playing(): st.voice.stop(); await i.response.send_message("Skipped.")
    else: await i.response.send_message("Nothing is playing.", ephemeral=True)
@bot.tree.command(name="stop", description="Stop and clear")
async def stop(i):
    st=get_state(i.guild_id); st.queue.clear(); st.current=None
    if st.voice: st.voice.stop()
    await i.response.send_message("Stopped and cleared.")
@bot.tree.command(name="shuffle", description="Shuffle queue")
async def shuffle(i): random.shuffle(get_state(i.guild_id).queue); await i.response.send_message("Queue shuffled.")
@bot.tree.command(name="volume", description="Set volume")
async def volume(i, amount: app_commands.Range[int,0,100]):
    st=get_state(i.guild_id); st.volume=amount
    if st.voice and isinstance(st.voice.source, discord.PCMVolumeTransformer): st.voice.source.volume=amount/100
    await i.response.send_message(f"Volume: **{amount}%**")
@bot.tree.command(name="loop", description="Toggle loop")
async def loop(i):
    st=get_state(i.guild_id); st.loop=not st.loop; await i.response.send_message(f"Loop: **{'ON' if st.loop else 'OFF'}**")
@bot.tree.command(name="autoplay", description="Toggle autoplay")
async def autoplay(i):
    st=get_state(i.guild_id); st.autoplay=not st.autoplay; await i.response.send_message(f"Autoplay: **{'ON' if st.autoplay else 'OFF'}**")
@bot.tree.command(name="filter", description="Choose filter")
@app_commands.choices(name=[app_commands.Choice(name=k,value=k) for k in FILTERS])
async def filter_cmd(i, name: app_commands.Choice[str]):
    st=get_state(i.guild_id); st.filter_name=name.value; await i.response.send_message(f"Filter set to **{name.value}**. It applies to the next track.")
@bot.tree.command(name="remove", description="Remove queue item")
async def remove(i, position: app_commands.Range[int,1,1000]):
    st=get_state(i.guild_id)
    if position>len(st.queue): return await i.response.send_message("Invalid position.", ephemeral=True)
    t=st.queue.pop(position-1); await i.response.send_message(f"Removed **{t.title}**")
@bot.tree.command(name="clear", description="Clear queue")
async def clear(i):
    st=get_state(i.guild_id); n=len(st.queue); st.queue.clear(); await i.response.send_message(f"Cleared **{n}** tracks.")
@bot.tree.command(name="disconnect", description="Leave voice")
async def disconnect(i):
    st=get_state(i.guild_id); st.queue.clear(); st.current=None
    if st.voice: await st.voice.disconnect(force=True); st.voice=None
    await i.response.send_message("Disconnected.")

@bot.tree.command(name="playlist_save", description="Save queue as playlist")
async def playlist_save(i, name: str):
    st=get_state(i.guild_id); data=load_data(); data[f"{i.guild_id}:{name.lower()}"]=[t.webpage for t in st.queue]; save_data(data); await i.response.send_message(f"Saved playlist **{name}**.")
@bot.tree.command(name="playlist_load", description="Load playlist")
async def playlist_load(i, name: str):
    await i.response.defer(); st=await connect_voice(i)
    if not st: return
    urls=load_data().get(f"{i.guild_id}:{name.lower()}", [])
    for url in urls:
        try: st.queue.append(await resolve(url, str(i.user)))
        except Exception: pass
    await i.followup.send(f"Loaded **{len(urls)}** playlist entries.")
    if not st.voice.is_playing(): await advance(i.guild)
@bot.tree.command(name="playlist_list", description="List playlists")
async def playlist_list(i):
    prefix=f"{i.guild_id}:"; names=[k.split(":",1)[1] for k in load_data() if k.startswith(prefix)]; await i.response.send_message("📚 " + ("\n".join(names) if names else "No playlists."))
@bot.tree.command(name="playlist_delete", description="Delete playlist")
async def playlist_delete(i, name: str):
    data=load_data(); key=f"{i.guild_id}:{name.lower()}"
    if key not in data: return await i.response.send_message("Playlist not found.", ephemeral=True)
    del data[key]; save_data(data); await i.response.send_message(f"Deleted **{name}**.")

bot.run(TOKEN)

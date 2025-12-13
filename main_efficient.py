# main.py - Streamlined HootBot
import asyncio
import discord
from discord.ext import commands
import yt_dlp
import re
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from typing import Optional, Dict, Any

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
DEBUG = False
IDLE_TIMEOUT = 30
Current_volume = 0.1
TOKEN = os.environ.get('DISCORD_TOKEN', 'YOUR_TOKEN_HERE')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
file_handler = RotatingFileHandler('hootsbot.log', maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
logging.getLogger().addHandler(file_handler)
logger = logging.getLogger('hootsbot')

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@dataclass
class QueueEntry:
    url: str
    title: str
    requester_id: int
    info: Optional[Dict] = None

class MusicBot:
    def __init__(self):
        self.queue = []
        self.current_track = None
        self.ytdl = yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True})
        self.downloaded_files = set()
        self.locks = {}
        self.timeout_tasks = {}
        
    def get_ffmpeg_options(self):
        opts = {
            'before_options': '-nostdin -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10',
            'options': '-vn -hide_banner -loglevel info'
        }
        if DEBUG:
            opts['options'] += ' -report'
        return opts
    
    async def extract_info(self, url):
        """Extract video information."""
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            if info:
                # Simple SABR detection
                formats = info.get('formats', [])
                with_url = sum(1 for f in formats if f and f.get('url'))
                info['_needs_download'] = len(formats) > 0 and with_url * 3 < len(formats)
                logger.info(f'Extracted {url}: {len(formats)} formats, {with_url} with URLs')
            return info
        except Exception as e:
            logger.error(f'Extraction failed for {url}: {e}')
            return None
    
    def select_format(self, info):
        """Select best audio format."""
        formats = info.get('formats', [])
        if not formats:
            return None, False
        
        # Find best audio format
        best = None
        best_score = -1
        
        for f in formats:
            if not f or not f.get('url') or f.get('acodec') in (None, 'none'):
                continue
            
            # Prefer non-fragmented formats
            is_fragmented = bool(f.get('fragments') or f.get('fragment_base_url') or 
                               (f.get('protocol', '') in ('m3u8', 'dash')))
            
            score = f.get('abr', 0) or f.get('tbr', 0)
            if not is_fragmented:
                score += 1000  # Heavily prefer progressive
            
            if score > best_score:
                best_score = score
                best = f
        
        if best:
            is_frag = bool(best.get('fragments') or best.get('fragment_base_url') or 
                          (best.get('protocol', '') in ('m3u8', 'dash')))
            return best.get('url'), is_frag
        
        return None, False
    
    async def download_audio(self, url, title="Unknown"):
        """Download audio for problematic streams."""
        try:
            loop = asyncio.get_event_loop()
            download_info = await loop.run_in_executor(
                None, lambda: self.ytdl.extract_info(url, download=True)
            )
            filename = self.ytdl.prepare_filename(download_info)
            if filename and os.path.exists(filename):
                abs_path = os.path.abspath(filename)
                self.downloaded_files.add(abs_path)
                return abs_path, download_info
        except Exception as e:
            logger.error(f'Download failed for {url}: {e}')
        return None, None
    
    def add_to_queue(self, url, title, requester_id):
        """Add entry to queue."""
        entry = QueueEntry(url=url, title=title, requester_id=requester_id)
        self.queue.append(entry)
        return entry
    
    def get_queue_display(self):
        """Get formatted queue display."""
        if not self.queue:
            return "The queue is currently empty."
        
        items = [f"{i+1}. {entry.title}" for i, entry in enumerate(self.queue)]
        return "**Current Queue:**\n" + "\n".join(items)
    
    def clear_queue(self):
        """Clear queue and return count."""
        count = len(self.queue)
        self.queue.clear()
        self.current_track = None
        return count
    
    async def get_guild_lock(self, guild_id):
        """Get per-guild async lock."""
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        return self.locks[guild_id]
    
    async def cleanup_file(self, filepath):
        """Remove downloaded file."""
        try:
            def _remove():
                if os.path.exists(filepath):
                    os.remove(filepath)
            await asyncio.get_event_loop().run_in_executor(None, _remove)
            self.downloaded_files.discard(filepath)
        except:
            pass

# Global bot instance
music_bot = MusicBot()

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data=None):
        super().__init__(source, volume=Current_volume)
        self.data = data or {}
        self.title = self.data.get('title', 'Unknown')

def has_multiple_commands(text):
    """Check for multiple commands in message."""
    if not text:
        return False
    return len(re.findall(r'(?<!\S)![A-Za-z]+', text)) > 1

async def reject_multiple_commands(ctx):
    """Reject messages with multiple commands."""
    if has_multiple_commands(getattr(ctx.message, 'content', '')):
        await ctx.send("Please use one command at a time.")
        return True
    return False

def extract_video_id_from_playlist(url):
    """Extract video ID from playlist URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get('v', [None])[0]
    except:
        return None

def is_playlist_url(url):
    """Check if URL is a playlist."""
    return 'list=' in url or ('playlist' in url and 'watch' in url)

async def play_audio(ctx, entry):
    """Play audio for a queue entry."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        return False
    
    music_bot.current_track = entry
    
    # Get info if needed
    if not entry.info:
        entry.info = await music_bot.extract_info(entry.url)
        if not entry.info:
            await ctx.send(f"Failed to extract: **{entry.title}**")
            return False
    
    # Determine playback method
    stream_url, is_fragmented = music_bot.select_format(entry.info)
    needs_download = entry.info.get('_needs_download', False) or is_fragmented or not stream_url
    
    try:
        if needs_download:
            # Download and play local file
            reason = "SABR/streaming issues" if entry.info.get('_needs_download') else "fragmented format"
            await ctx.send(f"Auto-downloading **{entry.title}** due to {reason}")
            
            filepath, download_info = await music_bot.download_audio(entry.url, entry.title)
            if filepath:
                source = YTDLSource(
                    discord.FFmpegPCMAudio(filepath, **music_bot.get_ffmpeg_options()),
                    data=download_info
                )
                voice_client.play(source, after=lambda e: asyncio.create_task(
                    playback_finished(ctx, e, filepath)
                ))
                await ctx.send(f"**Now playing:** {entry.title}")
                return True
        else:
            # Stream directly
            source = YTDLSource(
                discord.FFmpegPCMAudio(stream_url, **music_bot.get_ffmpeg_options()),
                data=entry.info
            )
            voice_client.play(source, after=lambda e: asyncio.create_task(
                playback_finished(ctx, e)
            ))
            await ctx.send(f"**Now playing:** {entry.title}")
            return True
    except Exception as e:
        logger.error(f"Playback failed: {e}")
        await ctx.send(f"Playback failed: {str(e)}")
    
    return False

async def playback_finished(ctx, error, filepath=None):
    """Handle playback completion."""
    if error:
        logger.error(f"Playback error: {error}")
    
    if filepath:
        await music_bot.cleanup_file(filepath)
    
    await play_next(ctx)

async def play_next(ctx):
    """Play next song in queue."""
    guild_id = ctx.guild.id
    
    async with await music_bot.get_guild_lock(guild_id):
        # Cancel idle timeout
        if guild_id in music_bot.timeout_tasks:
            music_bot.timeout_tasks[guild_id].cancel()
            del music_bot.timeout_tasks[guild_id]
        
        # Get next entry
        if not music_bot.queue:
            # Start idle timeout
            music_bot.timeout_tasks[guild_id] = asyncio.create_task(handle_idle(ctx))
            return
        
        entry = music_bot.queue.pop(0)
        success = await play_audio(ctx, entry)
        
        if not success and music_bot.queue:
            # Try next song if current failed
            await play_next(ctx)

async def handle_idle(ctx):
    """Handle idle timeout."""
    await asyncio.sleep(IDLE_TIMEOUT)
    voice_client = ctx.guild.voice_client
    if voice_client and not voice_client.is_playing() and not music_bot.queue:
        await ctx.send("Leaving due to inactivity.")
        await leave_voice(ctx)

async def leave_voice(ctx):
    """Leave voice channel and cleanup."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        return
    
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    count = music_bot.clear_queue()
    
    # Cancel timeout
    guild_id = ctx.guild.id
    if guild_id in music_bot.timeout_tasks:
        music_bot.timeout_tasks[guild_id].cancel()
        del music_bot.timeout_tasks[guild_id]
    
    await voice_client.disconnect()
    return count

# Bot Commands
@bot.command(name='join')
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    await ctx.author.voice.channel.connect()
    
    # Set volume
    vc = ctx.guild.voice_client
    if vc and hasattr(vc, 'source') and vc.source:
        vc.source.volume = Current_volume

@bot.command(name='leave')
async def leave(ctx):
    count = await leave_voice(ctx)
    if count is None:
        await ctx.send("Not connected to a voice channel.")
    elif count > 0:
        await ctx.send(f"Left voice channel and cleared {count} song(s).")
    else:
        await ctx.send("Left voice channel.")

@bot.command(name='play')
async def play(ctx, *, url):
    if await reject_multiple_commands(ctx):
        return
    
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    # Join if needed
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client
    
    await ctx.send("Processing...")
    
    # Handle playlist URLs - extract specific video
    if is_playlist_url(url):
        video_id = extract_video_id_from_playlist(url)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Extract info
    info = await music_bot.extract_info(url)
    if not info:
        await ctx.send("Could not extract information.")
        return
    
    title = info.get('title', 'Unknown')
    entry = music_bot.add_to_queue(url, title, ctx.author.id)
    entry.info = info
    
    if DEBUG:
        logger.debug(f"Queued: {title}")
    
    # Start playback if idle
    if not voice_client.is_playing():
        await play_next(ctx)
    else:
        await ctx.send(f"Added **{title}** to queue.")

@bot.command(name='queue')
async def show_queue(ctx):
    await ctx.send(music_bot.get_queue_display())

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    if not music_bot.current_track:
        await ctx.send("Nothing is currently playing.")
        return
    
    track = music_bot.current_track
    await ctx.send(f"**Now playing:** {track.title}\nRequested by: <@{track.requester_id}>")

@bot.command(name='skip', aliases=['next'])
async def skip(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await ctx.send("Skipped!")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='pause')
async def pause(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Paused.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='resume')
async def resume(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Resumed.")
    else:
        await ctx.send("Nothing is paused.")

@bot.command(name='stop')
async def stop(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("Stopped.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='volume')
async def volume(ctx, value: int):
    if not 0 <= value <= 100:
        await ctx.send("Volume must be between 0-100.")
        return
    
    global Current_volume
    Current_volume = value / 100.0
    
    voice_client = ctx.guild.voice_client
    if voice_client and hasattr(voice_client, 'source') and voice_client.source:
        voice_client.source.volume = Current_volume
    
    await ctx.send(f"Volume set to {value}%.")

@bot.command(name='debug')
async def toggle_debug(ctx, mode: str = None):
    global DEBUG
    if mode is None:
        await ctx.send(f"Debug is {'ON' if DEBUG else 'OFF'}.")
        return
    
    if mode.lower() in ('on', '1', 'true'):
        DEBUG = True
        logging.getLogger().setLevel(logging.DEBUG)
        await ctx.send("Debug enabled.")
    elif mode.lower() in ('off', '0', 'false'):
        DEBUG = False
        logging.getLogger().setLevel(logging.INFO)
        await ctx.send("Debug disabled.")
    else:
        await ctx.send("Use 'on' or 'off'.")

@bot.command(name='skeet')
async def skeet(ctx):
    """Who is a bitch?"""
    await ctx.send("@skeetanese , Is you the bitch ?")

@bot.event
async def on_ready():
    logger.info(f'Bot ready: {bot.user}')
    print(f'Logged in as {bot.user}')

if __name__ == '__main__':
    print('Starting HootBot...')
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f'Bot failed to start: {e}')
        logger.error(f'Startup failed: {e}')
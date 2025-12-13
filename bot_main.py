# bot_main.py - Streamlined main bot file
import asyncio
import discord
from discord.ext import commands
import re
from urllib.parse import urlparse, parse_qs

# Import our modules
from config import setup_logging, TOKEN, DEBUG, IDLE_TIMEOUT_SECONDS, Current_volume
from audio_manager import AudioManager
from queue_manager import QueueManager, QueueEntry

# Setup
logger = setup_logging()
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
audio_manager = AudioManager(logger)
queue_manager = QueueManager(logger)

# Global state
timeout_tasks = {}

# Utility functions
def has_multiple_commands(text: str) -> bool:
    """Check if message contains multiple bot commands."""
    if not text:
        return False
    hits = re.findall(r'(?<!\S)!(?:[A-Za-z]+)', text)
    return len(hits) > 1

async def reject_multiple_commands(ctx) -> bool:
    """Reject messages with multiple commands."""
    if has_multiple_commands(getattr(ctx.message, 'content', None)):
        await ctx.send("Please use one command at a time.")
        return True
    return False

def is_playlist_url(url: str) -> bool:
    """Check if URL is a playlist."""
    return isinstance(url, str) and ('list=' in url or ('playlist' in url and 'watch' in url))

def extract_video_id(url: str) -> str:
    """Extract video ID from playlist URL."""
    try:
        qp = parse_qs(urlparse(url).query)
        return qp.get('v', [None])[0]
    except:
        return None

# Playback logic
async def play_entry(ctx, entry: QueueEntry):
    """Play a single queue entry."""
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return False
    
    queue_manager.current_track = entry
    
    # Get audio info if not cached
    if not entry.info:
        entry.info = await audio_manager.extract_info(entry.url)
        if not entry.info:
            await ctx.send(f"Failed to extract: **{entry.title}**")
            return False
    
    # Determine if we need to download
    stream_url, format_meta, is_fragmented = audio_manager.select_best_format(entry.info)
    sabr_affected = entry.info.get('_sabr_affected', False)
    
    should_download = (
        not stream_url or 
        sabr_affected or 
        (is_fragmented and audio_manager.ytdl.params.get('force_download_fragments', True))
    )
    
    try:
        if should_download:
            # Download and play local file
            reason = "SABR issues" if sabr_affected else "fragmented format" if is_fragmented else "no stream URL"
            await ctx.send(f"Auto-downloading **{entry.title}** due to {reason}")
            
            filepath, download_info = await audio_manager.download_and_prepare(entry.url, entry.title)
            if filepath:
                source = audio_manager.create_audio_source(filepath, download_info)
                voice_client.play(source, after=lambda e: asyncio.create_task(
                    handle_playback_end(ctx, e, filepath)
                ))
                await ctx.send(f"**Now playing:** {entry.title}")
                return True
        else:
            # Stream directly
            source = audio_manager.create_audio_source(stream_url, entry.info)
            voice_client.play(source, after=lambda e: asyncio.create_task(
                handle_playback_end(ctx, e)
            ))
            await ctx.send(f"**Now playing:** {entry.title}")
            return True
            
    except Exception as e:
        logger.error(f"Playback failed: {e}")
        await ctx.send(f"Playback failed for **{entry.title}**: {str(e)}")
    
    return False

async def handle_playback_end(ctx, error, filepath=None):
    """Handle end of playback."""
    if error:
        logger.error(f"Playback error: {error}")
    
    # Cleanup downloaded file
    if filepath:
        await audio_manager.cleanup_file(filepath)
    
    # Play next in queue
    await play_next_in_queue(ctx)

async def play_next_in_queue(ctx):
    """Play next song in queue."""
    guild_id = ctx.guild.id
    
    # Skip if retry is scheduled
    if queue_manager.is_retry_scheduled(guild_id):
        return
    
    async with await queue_manager.get_guild_lock(guild_id):
        # Cancel idle timeout
        if guild_id in timeout_tasks:
            timeout_tasks[guild_id].cancel()
            del timeout_tasks[guild_id]
        
        # Get next entry
        entry = queue_manager.get_next_entry()
        if not entry:
            # Start idle timeout
            timeout_tasks[guild_id] = asyncio.create_task(handle_idle_timeout(ctx))
            return
        
        # Play the entry
        success = await play_entry(ctx, entry)
        if not success:
            # If failed, try next
            await play_next_in_queue(ctx)

async def handle_idle_timeout(ctx):
    """Handle idle timeout."""
    await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
    voice_client = ctx.guild.voice_client
    if voice_client and not voice_client.is_playing() and not queue_manager.queue:
        await ctx.send("Leaving due to inactivity.")
        await leave(ctx)

# Bot commands
@bot.command(name='join')
async def join(ctx):
    """Join voice channel."""
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    channel = ctx.author.voice.channel
    await channel.connect()
    
    # Set volume
    vc = ctx.guild.voice_client
    if vc and hasattr(vc, 'source') and vc.source:
        vc.source.volume = Current_volume

@bot.command(name='leave')
async def leave(ctx):
    """Leave voice channel and clean up."""
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        await ctx.send("Not connected to a voice channel.")
        return
    
    # Stop playback and clear queue
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    count = queue_manager.clear_queue()
    
    # Cancel timeouts and clear retry markers
    guild_id = ctx.guild.id
    if guild_id in timeout_tasks:
        timeout_tasks[guild_id].cancel()
        del timeout_tasks[guild_id]
    
    queue_manager.clear_retry_scheduled(guild_id)
    
    await voice_client.disconnect()
    
    if count > 0:
        await ctx.send(f"Left voice channel and cleared {count} song(s).")
    else:
        await ctx.send("Left voice channel.")

@bot.command(name='play')
async def play(ctx, *, url):
    """Play a song or playlist item."""
    if await reject_multiple_commands(ctx):
        return
    
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    # Join if not connected
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client
    
    await ctx.send("Processing your request...")
    
    # Handle playlist URLs with video ID
    if is_playlist_url(url):
        video_id = extract_video_id(url)
        if video_id:
            # Use direct video URL instead of playlist
            url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Extract info and add to queue
    info = await audio_manager.extract_info(url)
    if not info:
        await ctx.send("Could not extract information for the requested URL.")
        return
    
    title = info.get('title', 'Unknown')
    entry = queue_manager.add_entry(url, title, ctx.author.id)
    entry.info = info  # Cache the info
    
    if DEBUG:
        logger.debug(f"Queued: {title} by {ctx.author.id}")
    
    # Start playback if nothing playing
    if not voice_client.is_playing():
        await play_next_in_queue(ctx)
    else:
        await ctx.send(f"Added **{title}** to the queue.")

@bot.command(name='queue')
async def show_queue(ctx):
    """Show current queue."""
    await ctx.send(queue_manager.get_queue_display())

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    """Show currently playing track."""
    if not queue_manager.current_track:
        await ctx.send("Nothing is currently playing.")
        return
    
    track = queue_manager.current_track
    await ctx.send(f"**Now playing:** {track.title}\nRequested by: <@{track.requester_id}>")

@bot.command(name='skip', aliases=['next'])
async def skip(ctx):
    """Skip current track."""
    voice_client = ctx.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await ctx.send("Skipped!")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='pause')
async def pause(ctx):
    """Pause playback."""
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Paused.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='resume')
async def resume(ctx):
    """Resume playback."""
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Resumed.")
    else:
        await ctx.send("Nothing is paused.")

@bot.command(name='stop')
async def stop(ctx):
    """Stop playback."""
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("Stopped.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='volume')
async def volume(ctx, value: int):
    """Set volume (0-100)."""
    if not 0 <= value <= 100:
        await ctx.send("Volume must be between 0 and 100.")
        return
    
    global Current_volume
    Current_volume = value / 100.0
    
    voice_client = ctx.guild.voice_client
    if voice_client and hasattr(voice_client, 'source') and voice_client.source:
        voice_client.source.volume = Current_volume
    
    await ctx.send(f"Volume set to {value}%.")

@bot.command(name='debug')
async def toggle_debug(ctx, mode: str = None):
    """Toggle debug mode."""
    global DEBUG
    if mode is None:
        await ctx.send(f"Debug is {'ON' if DEBUG else 'OFF'}.")
        return
    
    if mode.lower() in ('on', '1', 'true'):
        DEBUG = True
        await ctx.send("Debug enabled.")
    elif mode.lower() in ('off', '0', 'false'):
        DEBUG = False
        await ctx.send("Debug disabled.")
    else:
        await ctx.send("Use 'on' or 'off'.")

# Skeet command (keep as requested)
@bot.command(name='skeet')
async def skeet(ctx):
    """Who is a bitch?"""
    await ctx.send("@skeetanese , Is you the bitch ?")

@bot.event
async def on_ready():
    """Bot ready event."""
    logger.info(f'Bot ready: {bot.user} (ID: {bot.user.id})')
    print(f'Logged in as {bot.user}')

if __name__ == '__main__':
    print('Starting HootBot...')
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f'Bot failed to start: {e}')
        logger.error(f'Bot startup failed: {e}')
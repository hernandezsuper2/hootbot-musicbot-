"""Playing songs, advancing the queue, idle leave and voice reconnect."""
import asyncio
import os
import random
from typing import Optional

import discord

from .config import logger, ULTRA_FAST, FORCE_DOWNLOAD, FORCE_DOWNLOAD_FRAGMENTED, IDLE_TIMEOUT, BOT_OUTPUT_CHANNEL_ID
from .core import bot
from .music import music_bot, QueueEntry
from .sources import YTDLSource, ChannelContext

# ============================================================================
# CONSTANTS
# ============================================================================

IDLE_MESSAGES = [
    "Leaving due to inactivity. Someone should consider portion control. 🍔",
    "Leaving due to inactivity. The gym membership is still waiting... 💪",
    "Leaving due to inactivity. Moderation is key, they say. 🍰",
    "Leaving due to inactivity. Maybe skip seconds next time? 🍕",
    "Leaving due to inactivity. Salad: it exists. 🥗",
    "Leaving due to inactivity. The treadmill misses you. 🏃",
    "Leaving due to inactivity. Someone's been hitting the buffet hard. 🍽️",
    "Leaving due to inactivity. Those pants aren't going to fit themselves. 👖",
    "Leaving due to inactivity. The elevator thanks you for your business. 🛗",
    "Leaving due to inactivity. Remember: sharing is caring. Especially dessert. 🧁",
    "Leaving due to inactivity. The fridge called. It's scared. 🧊",
    "Leaving due to inactivity. Your scale filed a restraining order. ⚖️",
    "Leaving due to inactivity. Diet starts Monday, right? 📅",
    "Leaving due to inactivity. The all-you-can-eat place is reconsidering their policy. 🍴",
    "Leaving due to inactivity. Your belt is waving a white flag. 🏳️",
    "Leaving due to inactivity. Someone discovered the snack drawer again. 🍪",
    "Leaving due to inactivity. Vegetables are just a suggestion, apparently. 🥦",
    "Leaving due to inactivity. The couch has a permanent you-shaped dent. 🛋️",
    "Leaving due to inactivity. Water? Never heard of her. 🥤",
    "Leaving due to inactivity. Those extra large shirts looking pretty medium now. 👕",
    "Leaving due to inactivity. The pizza delivery guy knows your order by heart. 🚗",
    "Leaving due to inactivity. Someone's been training for a hot dog eating contest. 🌭",
    "Leaving due to inactivity. The stairs vs. elevator debate is no longer a debate. 🎢",
    "Leaving due to inactivity. Your fitness tracker died of boredom. ⌚",
    "Leaving due to inactivity. The buffet installed a 'frequent visitor' plaque for you. 🏆"
]

# ============================================================================
# PLAYBACK FUNCTIONS
# ============================================================================

async def set_channel_status(guild, status: Optional[str]):
    """Set (or clear) the bot's voice channel status."""
    vc = guild.voice_client
    if not vc:
        return
    try:
        await guild._state.http.edit_voice_channel_status(status, channel_id=vc.channel.id)
    except Exception as e:
        logger.debug(f"Could not update channel status: {e}")

def _kick_preload():
    """Cancel any stale preload task and start a fresh one for the next song."""
    if music_bot.queue:
        if music_bot.preload_task and not music_bot.preload_task.done():
            music_bot.preload_task.cancel()
        music_bot.preload_task = asyncio.create_task(music_bot.preload_next_song())

async def wait_for_voice_idle(voice_client, max_wait=20):
    """Wait briefly if something (e.g. a welcome intro) is already playing, so play() doesn't fail."""
    waited = 0.0
    while voice_client.is_playing() and waited < max_wait:
        await asyncio.sleep(0.2)
        waited += 0.2

async def play_audio(ctx, entry):
    """Play audio for a queue entry - optimized for instant playback."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        logger.error(f"No voice client for {entry.title}")
        return False

    # Track text channel for reconnect
    if hasattr(ctx, 'channel') and ctx.channel:
        music_bot.last_text_channel[ctx.guild.id] = ctx.channel

    music_bot.current_track = entry
    
    # Use cached info if available, otherwise extract now (should be rare)
    if not entry.info:
        logger.info(f"No cached info, extracting for: {entry.title}")
        if ULTRA_FAST:
            entry.info = await music_bot.extract_info_fast(entry.url)
        else:
            entry.info = await music_bot.extract_info(entry.url)
    else:
        logger.info(f"Using cached info for: {entry.title}")
    
    if not entry.info:
        logger.error(f"Failed to extract info for: {entry.title}")
        await ctx.send(f"❌ **{entry.title}** is unavailable (may be region-restricted, private, or deleted)")
        return False
    
    # Get stream URL - prioritize instant streaming
    stream_url, is_fragmented = music_bot.select_format(entry.info)
    logger.info(f"Selected format for {entry.title}: stream_url={'Yes' if stream_url else 'No'}, fragmented={is_fragmented}")
    
    # Download if:
    # 1. FORCE_DOWNLOAD is True (user wants all downloads), OR
    # 2. FORCE_DOWNLOAD_FRAGMENTED is True AND format is fragmented (to ensure proper start), OR
    # 3. No stream URL available, OR
    # 4. SABR detection indicates download needed
    needs_download = (
        FORCE_DOWNLOAD or 
        (FORCE_DOWNLOAD_FRAGMENTED and is_fragmented) or
        not stream_url or
        entry.info.get('_needs_download', False)
    )
    
    try:
        if needs_download:
            # Download path - ensures proper start at 0:00
            if entry.info.get('_needs_download'):
                reason = "SABR detection"
            elif is_fragmented:
                reason = "fragmented format (ensuring proper start)"
            elif not stream_url:
                reason = "no stream available"
            else:
                reason = "force download enabled"
            
            # Use preloaded file if available, otherwise download now
            if entry.filepath and os.path.exists(entry.filepath) and os.path.getsize(entry.filepath) >= 1000:
                filepath = entry.filepath
                download_info = entry.info
                logger.info(f"Using pre-downloaded file: {filepath}")
            else:
                filepath, download_info = await music_bot.download_audio(entry.url, entry.title, entry.info)

            if not filepath:
                logger.error(f"Download returned no filepath for {entry.title}")
                # Check if it's a 403 error
                await ctx.send(f"❌ Download failed for **{entry.title}**\n"
                              f"💡 If you see '403 Forbidden' errors, YouTube may be blocking requests.\n"
                              f"Try updating yt-dlp: `pip install -U yt-dlp`")
                return False
            
            if not os.path.exists(filepath):
                logger.error(f"Downloaded file does not exist: {filepath}")
                await ctx.send(f"❌ Downloaded file not found for **{entry.title}**")
                return False
            
            file_size = os.path.getsize(filepath)
            if file_size < 1000:
                logger.error(f"Downloaded file too small: {file_size} bytes")
                await ctx.send(f"❌ Downloaded file corrupted for **{entry.title}**")
                return False
            
            logger.info(f"Playing downloaded file: {filepath} ({file_size} bytes)")

            voice_client = ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                logger.info("Voice client gone after download — bot disconnected, skipping playback")
                return False

            await wait_for_voice_idle(voice_client)
            try:
                source = YTDLSource(
                    discord.FFmpegPCMAudio(filepath, **music_bot.get_ffmpeg_options(is_file=True)),
                    data=download_info
                )
                voice_client.play(source, after=music_bot.create_after_callback(ctx, filepath))
                await ctx.send(f"🎵 {entry.title}")
                await set_channel_status(ctx.guild, f"🎵 {entry.title[:100]}")
                logger.info(f"Successfully started playback of downloaded file: {entry.title}")
                _kick_preload()
                return True
            except Exception as play_error:
                logger.error(f"Failed to play downloaded file {filepath}: {play_error}", exc_info=True)
                await ctx.send(f"❌ Failed to play downloaded file for **{entry.title}**")
                return False
        
        # Stream directly (fast path - only if download not needed)
        if stream_url:
            logger.info(f"Streaming from URL: {entry.title}")

            voice_client = ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                logger.info("Voice client gone before streaming — bot disconnected, skipping playback")
                return False

            await wait_for_voice_idle(voice_client)
            try:
                source = YTDLSource(
                    discord.FFmpegPCMAudio(stream_url, **music_bot.get_ffmpeg_options(is_file=False)),
                    data=entry.info
                )
                voice_client.play(source, after=music_bot.create_after_callback(ctx))
                await ctx.send(f"🎵 {entry.title}")
                await set_channel_status(ctx.guild, f"🎵 {entry.title[:100]}")
                logger.info(f"Successfully started playback: {entry.title}")
                _kick_preload()
                return True
            except Exception as stream_error:
                logger.error(f"Stream playback error for {entry.title}: {stream_error}", exc_info=True)
                await ctx.send(f"❌ Stream error for **{entry.title}**: {str(stream_error)}")
                return False
        else:
            logger.error(f"No playable stream found for: {entry.title}")
            await ctx.send(f"❌ No playable stream found for **{entry.title}**")
            return False
    except Exception as e:
        logger.error(f"Playback failed for {entry.title}: {e}", exc_info=True)
        await ctx.send(f"❌ Playback failed for **{entry.title}**: {str(e)}")
    
    return False

async def playback_finished(ctx, error, filepath=None):
    """Handle playback completion."""
    try:
        if error:
            error_msg = str(error).strip()
            logger.error(f"Playback error: {error_msg}")
            
            # Check for specific error types
            if any(keyword in error_msg.lower() for keyword in ['connection', 'network', 'timeout', 'broken pipe', 'eof']):
                logger.info("Network-related error detected, will try next song")
            elif 'terminated' in error_msg.lower() or 'return code' in error_msg.lower():
                logger.info("FFmpeg termination detected, continuing to next song")
                # Check if it's the weird return code we saw
                if '2880417800' in error_msg:
                    logger.info("Detected unusual return code - possibly WebM format issue")
            else:
                logger.info(f"Other playback error: {error_msg}")
        else:
            logger.debug("Playback completed normally")
        
        if filepath:
            await music_bot.cleanup_file(filepath)
        
        # Reduced delay for faster transitions
        await asyncio.sleep(0.1)
        await play_next(ctx)
    except Exception as e:
        logger.error(f"Error in playback_finished: {e}")
        if filepath:
            try:
                await music_bot.cleanup_file(filepath)
            except:
                pass

async def play_next(ctx):
    """Play next song in queue."""
    guild_id = ctx.guild.id

    # Only one play_next loop per guild at a time. If a loop is already running
    # it will naturally pick up any newly queued songs.
    if guild_id in music_bot.play_next_running:
        return
    music_bot.play_next_running.add(guild_id)

    try:
        await _play_next_loop(ctx)
    finally:
        music_bot.play_next_running.discard(guild_id)

async def _play_next_loop(ctx):
    """Inner loop — only called from play_next."""
    guild_id = ctx.guild.id

    # Keep trying songs until we find one that works or run out of queue
    failed_songs = []

    while True:
        async with await music_bot.get_guild_lock(guild_id):
            # Cancel idle timeout
            if guild_id in music_bot.timeout_tasks:
                music_bot.timeout_tasks[guild_id].cancel()
                del music_bot.timeout_tasks[guild_id]
            
            # Get next entry
            if not music_bot.queue:
                if failed_songs:
                    logger.info(f"Queue empty after trying {len(failed_songs)} unavailable songs")
                    await ctx.send(f"❌ All songs in queue ({len(failed_songs)}) were unavailable or region-restricted.")
                else:
                    logger.info("Queue is empty, starting idle timeout")
                # Start idle timeout
                music_bot.timeout_tasks[guild_id] = asyncio.create_task(handle_idle(ctx))
                return
            
            entry = music_bot.queue.pop(0)
            logger.info(f"Playing next from queue: {entry.title} (Queue size: {len(music_bot.queue)})")
        
        # Bail out if the bot is no longer in a voice channel (e.g. idle timeout fired)
        if not ctx.guild.voice_client:
            logger.info("Voice client gone before playback — bot disconnected, stopping queue")
            return

        # Play outside the lock to avoid deadlock
        success = await play_audio(ctx, entry)

        if success:
            if failed_songs:
                logger.info(f"Successfully playing after skipping {len(failed_songs)} unavailable songs")
            return  # Successfully playing, exit

        # Bail out immediately if the voice client disappeared during play_audio
        if not ctx.guild.voice_client:
            logger.info("Voice client lost during playback — bot disconnected, stopping queue")
            return

        # Failed to play - track it and continue
        failed_songs.append(entry.title)
        logger.warning(f"Failed to play {entry.title}, total failed: {len(failed_songs)}")

        # If the voice client is stuck in a playing state, stop it so the next
        # attempt doesn't get "Already playing audio."
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await asyncio.sleep(0.5)

        # Only send message every 5 songs to avoid spam
        if len(failed_songs) % 5 == 1:
            await ctx.send(f"⏭️ Skipping unavailable songs... ({len(failed_songs)} skipped so far)")

        await asyncio.sleep(0.3)  # Small delay to avoid hammering

        # Continue loop to try next song

async def handle_idle(ctx):
    """Handle idle timeout."""
    await asyncio.sleep(IDLE_TIMEOUT)
    voice_client = ctx.guild.voice_client
    if (voice_client and not voice_client.is_playing() and not music_bot.queue
            and not music_bot.is_extracting_playlist):
        await ctx.send(random.choice(IDLE_MESSAGES))
        await leave_voice(ctx)

async def leave_voice(ctx):
    """Leave voice channel and cleanup."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        return
    
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    count = music_bot.clear_queue()
    
    # Cancel timeout — skip self-cancel when called from inside the idle task itself,
    # because cancelling the current task raises CancelledError at the next await
    # and would prevent voice_client.disconnect() from running.
    guild_id = ctx.guild.id
    if guild_id in music_bot.timeout_tasks:
        task = music_bot.timeout_tasks[guild_id]
        if task is not asyncio.current_task():
            task.cancel()
        del music_bot.timeout_tasks[guild_id]

    await set_channel_status(ctx.guild, None)
    await voice_client.disconnect()
    return count

# ============================================================================
# RECONNECT HELPER
# ============================================================================

async def resume_after_intro(guild):
    """After a standalone welcome intro: continue the queue, or start the normal idle timeout.

    Going through handle_idle -> leave_voice also clears current_track, so the
    disconnect isn't mistaken for a crash by the auto-reconnect logic.
    """
    text_channel = music_bot.last_text_channel.get(guild.id)
    if not text_channel and BOT_OUTPUT_CHANNEL_ID:
        text_channel = bot.get_channel(BOT_OUTPUT_CHANNEL_ID)
    ctx = ChannelContext(guild, text_channel)
    if music_bot.queue:
        await play_next(ctx)
    elif guild.id not in music_bot.play_next_running:
        old_task = music_bot.timeout_tasks.pop(guild.id, None)
        if old_task:
            old_task.cancel()
        music_bot.timeout_tasks[guild.id] = asyncio.create_task(handle_idle(ctx))

async def reconnect_and_resume(guild, channel):
    """Attempt to reconnect to voice and resume the queue after an unexpected disconnect."""
    await asyncio.sleep(3)  # Let Discord settle before reconnecting

    try:
        if not music_bot.queue and not music_bot.current_track:
            logger.info(f"Nothing to resume after reconnect in {guild.name}")
            return

        logger.info(f"Attempting voice reconnect in {guild.name} → {channel.name}")
        await channel.connect()
        logger.info(f"Reconnected to {channel.name}")

        text_channel = music_bot.last_text_channel.get(guild.id)

        # Re-queue current track at the front so it restarts cleanly
        if music_bot.current_track:
            music_bot.queue.insert(0, QueueEntry(
                url=music_bot.current_track.url,
                title=music_bot.current_track.title,
                requester_id=music_bot.current_track.requester_id
            ))
            music_bot.current_track = None

        if text_channel:
            await text_channel.send("🔄 Reconnected to voice channel, resuming playback...")
            await play_next(ChannelContext(guild, text_channel))
        else:
            logger.warning("No text channel stored for reconnect — playback not resumed")

    except asyncio.TimeoutError:
        logger.error(f"Voice reconnect timed out for {guild.name}")
    except Exception as e:
        logger.error(f"Failed to reconnect voice in {guild.name}: {e}")

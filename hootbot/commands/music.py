"""Voice and playback commands: .play, .playlist, .skip, .volume, ..."""
import asyncio

import discord

from .. import config
from ..config import logger, TRUSTED_BOTS
from ..core import bot
from ..music import music_bot, QueueEntry
from ..playback import play_next, leave_voice
from ..utils import reject_multiple_commands, is_playlist_url, extract_video_id_from_playlist

# ============================================================================
# BOT COMMANDS - Voice Control
# ============================================================================

@bot.command(name='join')
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return

    channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client

    # Check permissions before attempting to connect
    perms = channel.permissions_for(ctx.guild.me)
    if not perms.connect:
        msg = f"❌ I don't have permission to **connect** to **{channel.name}**. Please check the channel's role permissions."
        logger.warning(f"Missing CONNECT permission for channel '{channel.name}' (ID: {channel.id}) in guild '{ctx.guild.name}'")
        await ctx.send(msg)
        return
    if not perms.speak:
        msg = f"❌ I don't have permission to **speak** in **{channel.name}**. Please check the channel's role permissions."
        logger.warning(f"Missing SPEAK permission for channel '{channel.name}' (ID: {channel.id}) in guild '{ctx.guild.name}'")
        await ctx.send(msg)
        return

    try:
        if voice_client:
            if voice_client.channel == channel:
                return  # Already in the right channel, nothing to do
            await voice_client.move_to(channel)
        else:
            await channel.connect()
    except asyncio.TimeoutError:
        logger.error(f"Timed out connecting to channel '{channel.name}' (ID: {channel.id}) in guild '{ctx.guild.name}'")
        await ctx.send("❌ Timed out connecting to voice channel. Please try again.")
        return
    except discord.ClientException as e:
        logger.error(f"ClientException connecting to channel '{channel.name}' in guild '{ctx.guild.name}': {e}")
        await ctx.send(f"❌ Could not connect to voice channel: {e}")
        return

@bot.command(name='playfor')
async def playfor(ctx, *, args: str):
    """Used by trusted bots: !playfor <channel-name> | <song>. Joins the named channel and plays."""
    if '|' not in args:
        await ctx.send("❌ Usage: `.playfor <channel name> | <song>`")
        return
    channel_name, query = [part.strip() for part in args.split('|', 1)]
    print(f"[playfor] Invoked by {ctx.author} (ID: {ctx.author.id}), channel='{channel_name}', query='{query}'", flush=True)
    logger.info(f"[playfor] Invoked by {ctx.author} (ID: {ctx.author.id}), channel='{channel_name}', query='{query}'")
    if ctx.author.id not in TRUSTED_BOTS:
        await ctx.send("❌ This command is only available to trusted bots.")
        return

    # Find voice channel by name (case-insensitive)
    channel = discord.utils.find(
        lambda c: isinstance(c, discord.VoiceChannel) and c.name.lower() == channel_name.lower(),
        ctx.guild.channels
    )
    if not channel:
        await ctx.send(f"❌ Could not find voice channel: **{channel_name}**")
        logger.warning(f"[playfor] Channel '{channel_name}' not found in guild '{ctx.guild.name}'")
        return

    # Permission check
    perms = channel.permissions_for(ctx.guild.me)
    if not perms.connect or not perms.speak:
        await ctx.send(f"❌ Missing connect/speak permissions in **{channel.name}**.")
        logger.warning(f"[playfor] Missing permissions for channel '{channel.name}'")
        return

    # Join channel
    voice_client = ctx.guild.voice_client
    try:
        if voice_client:
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
        else:
            await channel.connect()
        voice_client = ctx.guild.voice_client
    except Exception as e:
        await ctx.send(f"❌ Could not join **{channel.name}**: {e}")
        logger.error(f"[playfor] Failed to join '{channel.name}': {e}")
        return

    logger.info(f"[playfor] Joined '{channel.name}', resolving: {query}")

    try:
        # Resolve search or URL
        if not query.startswith('http://') and not query.startswith('https://'):
            logger.info(f"[playfor] Searching YouTube for: {query}")
            results = await music_bot.search_youtube(query, max_results=1)
            if not results:
                await ctx.send(f"❌ No results found for: **{query}**")
                logger.warning(f"[playfor] No search results for: {query}")
                return
            url = results[0]['url']
            logger.info(f"[playfor] Search resolved to: {url}")
        else:
            url = query

        logger.info(f"[playfor] Extracting info for: {url}")
        info = await music_bot.extract_info_fast(url)
        if not info:
            await ctx.send("❌ Could not extract video info.")
            logger.warning(f"[playfor] extract_info_fast returned None for: {url}")
            return

        title = info.get('title', 'Unknown')
        logger.info(f"[playfor] Queuing: {title}")
        entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)
        music_bot.queue.append(entry)
    except Exception as e:
        await ctx.send(f"❌ Error processing request: {e}")
        logger.error(f"[playfor] Unexpected error: {e}", exc_info=True)
        return

    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(ctx)
    else:
        await ctx.send(f"✅ Added **{title}** to queue.")

@bot.command(name='leave')
async def leave(ctx):
    count = await leave_voice(ctx)
    if count is None:
        await ctx.send("Not connected to a voice channel.")
    elif count > 0:
        await ctx.send(f"Left voice channel and cleared {count} song(s).")
    else:
        await ctx.send("Left voice channel.")

# ============================================================================
# BOT COMMANDS - Music Playback
# ============================================================================

@bot.command(name='play', aliases=['p'])
async def play(ctx, *, url):
    if await reject_multiple_commands(ctx):
        return
    
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    # Check if it's a search query (not a URL)
    if not url.startswith('http://') and not url.startswith('https://'):
        results = await music_bot.search_youtube(url, max_results=1)
        
        if not results:
            await ctx.send(f"❌ No results found for: **{url}**")
            return
        
        # Use the first result
        url = results[0]['url']
        # No message here, will show when playing
    
    # Check for YouTube Music URLs and give friendly reminder
    if 'music.youtube.com' in url:
        await ctx.send("💡 **Tip:** YouTube Music links don't work due to DRM. Please use regular YouTube links (youtube.com) instead! *(Specially you, Kat(twat))* 😊")
        return
    
    # Join if needed
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client

    if not voice_client:
        await ctx.send("❌ Could not connect to your voice channel.")
        return

    # Handle playlist URLs - extract specific video
    if is_playlist_url(url):
        video_id = extract_video_id_from_playlist(url)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Ultra-fast extraction - get full info immediately and cache it
    info = await music_bot.extract_info_fast(url)
    if not info:
        await ctx.send("❌ Could not extract information. The video may be a live stream, region-restricted, or unavailable.")
        return
    title = info.get('title', 'Unknown')
    # Create entry with cached info for instant playback
    entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)
    music_bot.queue.append(entry)
    
    if config.DEBUG:
        logger.debug(f"Queued: {title}")
    
    # Start playback if idle (but not if paused)
    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(ctx)
    else:
        await ctx.send(f"✅ Added **{title}** to queue.")

@bot.command(name='playnext', aliases=['pn'])
async def playnext(ctx, *, url):
    """Insert a song to be played next (front of the queue), or jump to a queue position."""
    if await reject_multiple_commands(ctx):
        return

    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return

    # Join voice if needed
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client

    # Check if url is a number (queue position)
    if url.strip().isdigit():
        position = int(url.strip())
        
        if not music_bot.queue:
            await ctx.send("❌ The queue is empty.")
            return
        
        if position < 1 or position > len(music_bot.queue):
            await ctx.send(f"❌ Invalid position. Queue has {len(music_bot.queue)} songs.")
            return
        
        # Get the song at that position
        target_song = music_bot.queue[position - 1]
        
        # Remove it from its current position
        music_bot.queue.pop(position - 1)
        
        # Insert it at the front
        music_bot.queue.insert(0, target_song)
        
        # Skip current song to play the target
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        
        await ctx.send(f"⏭️ Skipping to: **{target_song.title}**")
        return
    
    # Check if it's a search query (not a URL)
    if not url.startswith('http://') and not url.startswith('https://'):
        results = await music_bot.search_youtube(url, max_results=1)
        
        if not results:
            await ctx.send(f"❌ No results found for: **{url}**")
            return
        
        # Use the first result
        url = results[0]['url']

    await ctx.send("Processing (will play next)...")

    # Handle playlist URLs - extract specific video
    if is_playlist_url(url):
        video_id = extract_video_id_from_playlist(url)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"

    # Ultra-fast extraction with caching
    info = await music_bot.extract_info_fast(url)
    if not info:
        await ctx.send("❌ Could not extract information.")
        return
    title = info.get('title', 'Unknown')
    entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)

    # Insert next (front of queue)
    music_bot.queue.insert(0, entry)

    if config.DEBUG:
        logger.debug(f"Inserted to play next: {title}")

    # If nothing is playing and not paused, start playback immediately
    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(ctx)
    else:
        await ctx.send(f"⏭️ Will play next: **{title}**")

@bot.command(name='playlist', aliases=['pl'])
async def playlist(ctx, *, query: str):
    """Add multiple songs from a playlist/radio URL to the queue, or search for songs by artist."""
    if await reject_multiple_commands(ctx):
        return

    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    # Parse query to extract URL and optional max_songs number
    # Format: "URL" or "URL 30" or "artist name" or "artist name 15"
    parts = query.strip().split()
    url = parts[0] if parts else query
    max_songs = None  # Will be set based on URL vs search
    
    # Check if last part is a number (max_songs)
    if len(parts) > 1:
        try:
            max_songs = int(parts[-1])
            # If it's a number, the url/query is everything except the last part
            url = ' '.join(parts[:-1])
        except ValueError:
            # Not a number, so everything is the url/query
            url = query
    
    # Determine if it's a URL or search query
    is_url = url.startswith('http://') or url.startswith('https://')
    
    # Set default max_songs based on type if not specified
    if max_songs is None:
        if is_url:
            max_songs = 15  # Default 15 for playlist URLs
        else:
            max_songs = 15  # Default 15 for artist searches
    
    # Validate max_songs
    if max_songs < 1:
        max_songs = 1
    elif max_songs > 100:
        max_songs = 100
        await ctx.send(f"⚠️ Maximum 100 songs allowed, limiting to 100.")
    
    # Check if it's a search query (not a URL) - search for multiple songs
    if not is_url:
        # Join voice if needed
        voice_client = ctx.guild.voice_client
        if not voice_client:
            await join(ctx)
            voice_client = ctx.guild.voice_client
        
        # Check queue limit
        current_queue_size = len(music_bot.queue)
        target_songs = max_songs
        if current_queue_size + target_songs > 100:
            target_songs = 100 - current_queue_size
            if target_songs <= 0:
                await ctx.send(f"❌ Queue is full! Maximum 100 songs allowed. Current queue has {current_queue_size} songs.")
                return
            await ctx.send(f"⚠️ Queue limit reached. Adding only {target_songs} songs to reach the 100 song maximum.")
        # Record playback state before searching — search blocks for a few seconds
        should_start = not voice_client.is_playing() and not voice_client.is_paused()
        first_started = False

        # 2x target gives enough buffer for duplicates without over-fetching
        results = await music_bot.search_youtube(url, max_results=target_songs * 2)

        if not results:
            await ctx.send(f"❌ No results found for: **{url}**")
            return

        # Add results to queue; fire first song immediately, rest follow lazily
        added_count = 0
        skipped_duplicates = 0
        for result in results:
            if added_count >= target_songs:
                break

            try:
                if music_bot.is_duplicate_in_queue(result['title']):
                    logger.info(f"Skipped duplicate: {result['title']}")
                    skipped_duplicates += 1
                    continue

                entry = QueueEntry(
                    url=result['url'],
                    title=result['title'],
                    requester_id=ctx.author.id
                )
                music_bot.queue.append(entry)
                added_count += 1

                # Start playing the first song immediately without waiting for the rest
                if should_start and not first_started:
                    first_started = True
                    await play_next(ctx)

            except Exception as e:
                logger.error(f"Failed to queue search result: {e}")
                continue

        if added_count == 0:
            if skipped_duplicates > 0:
                await ctx.send(f"❌ All {skipped_duplicates} songs were already in the queue.")
            else:
                await ctx.send("❌ Could not add any songs to the queue.")
            return

        message = f"✅ Added **{added_count}** song(s)"
        if skipped_duplicates > 0:
            message += f" ({skipped_duplicates} duplicate(s) skipped)"
        await ctx.send(message)

        return
    
    # Check for YouTube Music URLs and give friendly reminder
    if 'music.youtube.com' in url:
        await ctx.send("💡 **Tip:** YouTube Music playlists don't work due to DRM. Please use regular YouTube playlists (youtube.com) instead! *(Especially you, Kat)* 😊")
        return

    # Join voice if needed
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client

    # Remember this playlist so !more can continue from where we left off
    music_bot.last_playlist_url = url
    music_bot.last_playlist_offset = 0

    # Extract all songs silently
    all_entries = await music_bot.extract_playlist(url, max_songs)
    
    if not all_entries or len(all_entries) == 0:
        await ctx.send("❌ Could not extract songs from playlist")
        return
    
    # Check if adding would exceed 100 song queue limit
    current_queue_size = len(music_bot.queue)
    if current_queue_size + len(all_entries) > 100:
        allowed = 100 - current_queue_size
        if allowed <= 0:
            await ctx.send(f"❌ Queue is full! Maximum 100 songs allowed. Current queue has {current_queue_size} songs.")
            return
        all_entries = all_entries[:allowed]
        await ctx.send(f"⚠️ Queue limit reached. Adding only {allowed} songs to reach the 100 song maximum.")
    
    # Track if we should start playback immediately
    should_start_playback = not voice_client.is_playing() and not voice_client.is_paused()
    first_song_added = False
    
    # Add all entries to queue (skip duplicates)
    added_count = 0
    skipped_duplicates = 0
    for entry_data in all_entries:
        try:
            # Check for duplicates before adding
            if music_bot.is_duplicate_in_queue(entry_data['title']):
                logger.info(f"Skipped duplicate: {entry_data['title']}")
                skipped_duplicates += 1
                continue
            
            entry = QueueEntry(
                url=entry_data['url'],
                title=entry_data['title'],
                requester_id=ctx.author.id
            )
            music_bot.queue.append(entry)
            added_count += 1
            
            # Start playing the first song immediately if nothing is playing
            if should_start_playback and not first_song_added:
                first_song_added = True
                await play_next(ctx)
                # Show immediate feedback
                await ctx.send(f"🎵 Playing first song, loading {len(all_entries) - 1} more...")
                
        except Exception as e:
            logger.error(f"Failed to queue entry: {e}")
            continue
    
    if added_count == 0:
        if skipped_duplicates > 0:
            await ctx.send(f"❌ All {skipped_duplicates} songs were already in the queue.")
        else:
            await ctx.send("❌ Could not add songs")
        return

    # Advance the offset so !more knows where to continue
    music_bot.last_playlist_offset += len(all_entries)

    # Show final summary message (only if we didn't already show the "Playing first song" message)
    if not first_song_added:
        message = f"✅ Added **{added_count}** song(s)"
        if skipped_duplicates > 0:
            message += f" ({skipped_duplicates} duplicate(s) skipped)"
        message += f" — use `.more` to load the next batch"
        await ctx.send(message)
    else:
        # Just show final count
        message = f"✅ Total: {added_count} songs added"
        if skipped_duplicates > 0:
            message += f" ({skipped_duplicates} duplicates skipped)"
        message += f" — use `.more` to load the next batch"
        await ctx.send(message)

@bot.command(name='more')
async def more(ctx, max_songs: int = 15):
    """Load the next batch of songs from the last playlist."""
    if await reject_multiple_commands(ctx):
        return

    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return

    if not music_bot.last_playlist_url:
        await ctx.send("❌ No playlist loaded yet. Use `.playlist <url>` first.")
        return

    voice_client = ctx.guild.voice_client
    if not voice_client:
        await join(ctx)
        voice_client = ctx.guild.voice_client

    if max_songs < 1:
        max_songs = 1
    elif max_songs > 100:
        max_songs = 100

    start = music_bot.last_playlist_offset + 1
    await ctx.send(f"⏳ Loading songs {start}–{start + max_songs - 1} from the playlist...")

    all_entries = await music_bot.extract_playlist(music_bot.last_playlist_url, max_songs, start=start)

    if not all_entries:
        await ctx.send("❌ No more songs found in the playlist.")
        return

    current_queue_size = len(music_bot.queue)
    if current_queue_size + len(all_entries) > 100:
        allowed = 100 - current_queue_size
        if allowed <= 0:
            await ctx.send(f"❌ Queue is full! ({current_queue_size}/100 songs)")
            return
        all_entries = all_entries[:allowed]
        await ctx.send(f"⚠️ Queue limit reached. Adding only {allowed} songs.")

    added_count = 0
    skipped_duplicates = 0
    for entry_data in all_entries:
        if music_bot.is_duplicate_in_queue(entry_data['title']):
            skipped_duplicates += 1
            continue
        music_bot.queue.append(QueueEntry(
            url=entry_data['url'],
            title=entry_data['title'],
            requester_id=ctx.author.id
        ))
        added_count += 1

    if added_count == 0:
        await ctx.send(f"❌ All {skipped_duplicates} songs were already in the queue." if skipped_duplicates else "❌ Could not add any songs.")
        return

    music_bot.last_playlist_offset += len(all_entries)

    message = f"✅ Added **{added_count}** more song(s)"
    if skipped_duplicates > 0:
        message += f" ({skipped_duplicates} duplicate(s) skipped)"
    message += f" — use `.more` again for the next batch"
    await ctx.send(message)

    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(ctx)

# ============================================================================
# BOT COMMANDS - Playback Control
# ============================================================================

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
    """Stop playback, clear queue, and leave voice channel."""
    if not ctx.guild.voice_client:
        await ctx.send("Not connected to a voice channel.")
        return

    count = await leave_voice(ctx)

    if count and count > 0:
        await ctx.send(f"⏹️ Stopped playback, cleared {count} song(s), and left voice channel.")
    else:
        await ctx.send("⏹️ Stopped playback and left voice channel.")

@bot.command(name='volume')
async def volume(ctx, value: int):
    if not 0 <= value <= 100:
        await ctx.send("Volume must be between 0-100.")
        return

    config.Current_volume = value / 100.0

    voice_client = ctx.guild.voice_client
    applied = False
    if voice_client and voice_client.source:
        try:
            voice_client.source.volume = config.Current_volume
            applied = True
        except Exception as e:
            logger.warning(f"Could not apply volume to current source: {e}")

    if applied:
        await ctx.send(f"🔊 Volume set to **{value}%** (applied to current song).")
    else:
        await ctx.send(f"🔊 Volume set to **{value}%** (will apply from next song).")

@bot.command(name='restart')
async def restart_current(ctx):
    """Restart the current song from the beginning."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await ctx.send("Not connected to voice channel.")
        return
    
    if not music_bot.current_track:
        await ctx.send("No current track to restart.")
        return
    
    # Stop current playback
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    # Re-add current track to front of queue
    current = music_bot.current_track
    music_bot.queue.insert(0, QueueEntry(
        url=current.url, 
        title=current.title, 
        requester_id=current.requester_id
    ))
    
    await ctx.send(f"Restarting **{current.title}** from the beginning...")
    
    # Small delay then play
    await asyncio.sleep(0.5)
    await play_next(ctx)

# ============================================================================
# BOT COMMANDS - Information & Help
# ============================================================================

@bot.command(name='status')
async def status(ctx):
    """Show detailed bot status for debugging."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await ctx.send("❌ Not connected to voice channel")
        return
    
    status_msg = "🎵 **Bot Status:**\n"
    status_msg += f"Connected: ✅ {voice_client.channel.name}\n"
    status_msg += f"Playing: {'✅' if voice_client.is_playing() else '❌'}\n"
    status_msg += f"Paused: {'✅' if voice_client.is_paused() else '❌'}\n"
    status_msg += f"Queue length: {len(music_bot.queue)}\n"
    
    if music_bot.current_track:
        status_msg += f"Current: {music_bot.current_track.title}\n"
    
    if voice_client.source:
        status_msg += f"Volume: {int(voice_client.source.volume * 100)}%\n"
    
    await ctx.send(status_msg)

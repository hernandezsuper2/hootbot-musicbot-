"""Queue commands: .queue, .remove, .shuffle."""
import random

from ..config import logger
from ..core import bot
from ..music import music_bot

# ============================================================================
# BOT COMMANDS - Queue Management
# ============================================================================

@bot.command(name='queue', aliases=['q'])
async def show_queue(ctx, arg: str = None):
    if arg and arg.lower() == 'all':
        if not music_bot.queue:
            await ctx.send("The queue is currently empty.")
            return
        lines = [f"**Current Queue ({len(music_bot.queue)} songs):**"]
        for i, entry in enumerate(music_bot.queue):
            lines.append(f"{i+1}. {entry.title}")
        # Split into ≤2000-char chunks
        chunk, chunks = "", []
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(music_bot.get_queue_display())

@bot.command(name='remove')
async def remove_from_queue(ctx, position: int):
    """Remove a song from the queue by position number.
    
    Usage: !remove 5  (removes the 5th song)
    """
    try:
        if not music_bot.queue:
            await ctx.send("❌ Queue is empty!")
            return
        
        # Convert to 0-based index
        index = position - 1
        
        if index < 0 or index >= len(music_bot.queue):
            await ctx.send(f"❌ Invalid position! Queue has {len(music_bot.queue)} song(s). Use positions 1-{len(music_bot.queue)}")
            return
        
        # Remove the song
        removed_entry = music_bot.queue.pop(index)
        
        await ctx.send(f"✅ Removed from queue (position {position}):\n**{removed_entry.title}**")
        logger.info(f"Removed from queue at position {position}: {removed_entry.title}")
        
    except ValueError:
        await ctx.send("❌ Invalid position! Use a number like: `.remove 5`")
    except Exception as e:
        logger.error(f"Error in remove command: {e}", exc_info=True)
        await ctx.send(f"❌ Error removing song: {str(e)}")

@bot.command(name='shuffle', aliases=['s'])
async def shuffle_queue(ctx):
    """Shuffle the queue when it has more than 10 songs."""
    try:
        if not music_bot.queue:
            await ctx.send("❌ Queue is empty!")
            return
        
        queue_length = len(music_bot.queue)
        
        if queue_length < 10:
            await ctx.send(f"❌ Queue only has {queue_length} song(s). Need at least 10 songs to shuffle.")
            return
        
        # Shuffle the queue
        random.shuffle(music_bot.queue)
        
        await ctx.send(f"🔀 **Shuffled {queue_length} songs in the queue!**")
        logger.info(f"Shuffled queue ({queue_length} songs)")
    except Exception as e:
        logger.error(f"Error in shuffle command: {e}", exc_info=True)
        await ctx.send(f"❌ Error shuffling queue: {str(e)}")

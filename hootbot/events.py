"""Discord event handlers."""
import asyncio

from discord.ext import commands

from .config import logger, TRUSTED_BOTS
from .core import bot, HootContext
from .music import music_bot
from .playback import reconnect_and_resume
from .welcome import handle_welcome

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.author.bot:
        if message.author.id not in TRUSTED_BOTS:
            return
        logger.info(f"[TrustedBot] Message from {message.author} (ID: {message.author.id}): {message.content}")
    ctx = await bot.get_context(message, cls=HootContext)
    await bot.invoke(ctx)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"[cmd_error] CommandNotFound: '{ctx.message.content}' from {ctx.author}")
    elif isinstance(error, commands.CheckFailure):
        logger.warning(f"[cmd_error] Not allowed: '{ctx.message.content}' from {ctx.author}")
        await ctx.send("❌ Only server admins can use that command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        logger.warning(f"[cmd_error] MissingArgument: '{ctx.message.content}' from {ctx.author} — {error}")
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    else:
        logger.error(f"[cmd_error] {type(error).__name__} in '{ctx.message.content}' from {ctx.author}: {error}", exc_info=error)

@bot.event
async def on_ready():
    """Called when bot is ready and connected"""
    logger.info(f'Bot ready: {bot.user}')
    print(f'Logged in as {bot.user}')
    
    # Start cleanup task
    await music_bot.start_cleanup_task()
    logger.info("Started file cleanup task")

@bot.event
async def on_voice_state_update(member, before, after):
    """Called when a user's voice state changes (join/leave/move)"""
    # Debug: Log all voice state changes
    logger.info(f'Voice state update: {member.name} (ID: {member.id}) - Before: {before.channel}, After: {after.channel}')
    
    # Handle bot's own voice state changes
    if member.bot:
        # Detect unexpected disconnect (was in a channel, now is not)
        if member == bot.user and before.channel is not None and after.channel is None:
            guild = before.channel.guild
            guild_id = guild.id
            if music_bot.queue or music_bot.current_track:
                logger.warning(f"Bot unexpectedly disconnected from voice in {guild.name}, scheduling reconnect")
                if guild_id in music_bot.reconnect_tasks:
                    music_bot.reconnect_tasks[guild_id].cancel()
                music_bot.reconnect_tasks[guild_id] = asyncio.create_task(
                    reconnect_and_resume(guild, before.channel)
                )
        return

    await handle_welcome(member, before, after)

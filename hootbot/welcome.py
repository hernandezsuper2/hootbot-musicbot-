"""The welcome-intro joke: plays a clip when one specific person joins a channel.

Off after every restart until an admin runs .welcomeon.
"""
import asyncio

import discord

from .config import logger, WELCOME_USER_ID, WELCOME_CHANNEL_NAME, WELCOME_SOUND_FILE
from .core import bot, admin_only
from .music import music_bot
from .playback import resume_after_intro
from .sources import IntroThenResume

async def handle_welcome(member, before, after):
    """Play the intro if WELCOME_USER_ID joined WELCOME_CHANNEL_NAME and welcome sounds are on."""
    # Only trigger for specific user
    if not WELCOME_USER_ID or member.id != WELCOME_USER_ID:
        logger.debug(f'Ignoring user {member.name} (not target user)')
        return
    
    # Check if welcome sounds are enabled for this guild
    guild_id = member.guild.id
    if not music_bot.welcome_enabled.get(guild_id, False):  # Default to disabled
        logger.info(f'Welcome sounds disabled for guild {guild_id}, skipping intro')
        return
    
    logger.info(f'Target user detected: {member.name} (ID: {member.id})')
    
    # Check if user joined the target channel (either from disconnect or from another channel)
    # They must not have been in the target channel before, but are in it now
    if after.channel is not None and after.channel.name == WELCOME_CHANNEL_NAME:
        # Make sure they weren't already in this channel (avoid triggering on mute/unmute etc)
        if before.channel != after.channel:
            logger.info(f'{member.name} joined {WELCOME_CHANNEL_NAME}, playing welcome sound')
            
            # Get the guild and check if bot is already in a voice channel
            guild = after.channel.guild
            voice_client = discord.utils.get(bot.voice_clients, guild=guild)
            
            # If bot is not connected, join the channel
            if voice_client is None:
                try:
                    voice_client = await after.channel.connect()
                    logger.info(f'Connected to {after.channel.name}')
                except Exception as e:
                    logger.error(f'Failed to connect to channel: {e}')
                    return
            # If bot is in a different channel, move to the welcome channel
            elif voice_client.channel != after.channel:
                try:
                    await voice_client.move_to(after.channel)
                    logger.info(f'Moved to {after.channel.name}')
                except Exception as e:
                    logger.error(f'Failed to move to channel: {e}')
                    return
            
            # Play the welcome sound. If a song is playing, splice the intro in front of
            # the rest of it instead of stopping it (stop() would advance the queue and lose the song).
            try:
                intro = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(WELCOME_SOUND_FILE), volume=0.20)

                if voice_client.is_playing():
                    voice_client.source = IntroThenResume(intro, voice_client.source)
                    logger.info(f'Playing intro for {member.name}, song resumes afterwards')
                    return
                if voice_client.is_paused():
                    intro.cleanup()
                    logger.info('Music is paused, skipping intro')
                    return

                def after_intro(error):
                    if error:
                        logger.error(f'Error during intro playback: {error}')
                    asyncio.run_coroutine_threadsafe(resume_after_intro(guild), bot.loop)

                voice_client.play(intro, after=after_intro)
                logger.info(f'Playing intro for {member.name}')
            except Exception as e:
                logger.error(f'Failed to play welcome sound: {e}')

# ============================================================================
# WELCOME SOUND TOGGLE COMMANDS
# ============================================================================

@bot.command(name='welcomeon', help='Enable welcome sounds when users join the voice channel')
@admin_only
async def welcome_on(ctx):
    """Enable welcome sounds for this server"""
    guild_id = ctx.guild.id
    music_bot.welcome_enabled[guild_id] = True
    await ctx.send('✅ Welcome sounds are now **enabled**! 🎵')
    logger.info(f'Welcome sounds enabled for guild {guild_id}')

@bot.command(name='welcomeoff', help='Disable welcome sounds when users join the voice channel')
@admin_only
async def welcome_off(ctx):
    """Disable welcome sounds for this server"""
    guild_id = ctx.guild.id
    music_bot.welcome_enabled[guild_id] = False
    await ctx.send('🔇 Welcome sounds are now **disabled**.')
    logger.info(f'Welcome sounds disabled for guild {guild_id}')

@bot.command(name='welcomestatus', help='Check if welcome sounds are enabled or disabled')
async def welcome_status(ctx):
    """Check the current welcome sound status for this server"""
    guild_id = ctx.guild.id
    is_enabled = music_bot.welcome_enabled.get(guild_id, False)  # Default to disabled
    status = "**enabled** ✅" if is_enabled else "**disabled** 🔇"
    await ctx.send(f'Welcome sounds are currently {status}')

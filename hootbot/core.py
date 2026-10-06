"""The Discord bot object and things every module needs from it."""
import discord
from discord.ext import commands

from .config import BOT_OUTPUT_CHANNEL_ID

# ============================================================================
# DISCORD BOT SETUP
# ============================================================================
intents = discord.Intents.default()

intents.message_content = True

intents.voice_states = True  # Enable voice state tracking

bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# Restricts maintenance commands to the bot's owner (Discord application owner) or server admins
admin_only = commands.check_any(commands.is_owner(), commands.has_permissions(administrator=True))

# ============================================================================
# BOT EVENTS
# ============================================================================

class HootContext(commands.Context):
    """Custom context that redirects all bot responses to the designated output channel."""
    async def send(self, *args, **kwargs):
        output_channel = self.bot.get_channel(BOT_OUTPUT_CHANNEL_ID) if BOT_OUTPUT_CHANNEL_ID else None
        if output_channel and self.channel.id != BOT_OUTPUT_CHANNEL_ID:
            return await output_channel.send(*args, **kwargs)
        return await super().send(*args, **kwargs)

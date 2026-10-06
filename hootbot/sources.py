"""Audio source wrappers and a minimal stand-in context."""
import discord

from . import config
from .config import logger

# ============================================================================
# HELPER CLASSES
# ============================================================================

class YTDLSource(discord.PCMVolumeTransformer):
    """Audio source wrapper for discord.py with volume control"""
    def __init__(self, source, *, data=None):
        super().__init__(source, volume=config.Current_volume)
        self.data = data or {}
        self.title = self.data.get('title', 'Unknown')

class IntroThenResume(discord.AudioSource):
    """Plays an intro clip, then continues the interrupted song from where it was.

    Swapped in via voice_client.source so the song's after-callback is untouched:
    no stop(), no lost song, and the queue advances normally when the song ends.
    """
    def __init__(self, intro, original):
        self.intro = intro
        self.original = original
        self.intro_done = False

    @property
    def volume(self):
        # .volume and .status act on the song, not the intro
        return self.original.volume

    @volume.setter
    def volume(self, value):
        self.original.volume = value

    def read(self):
        if not self.intro_done:
            data = self.intro.read()
            if data:
                return data
            self.intro_done = True
            self.intro.cleanup()
        return self.original.read()

    def is_opus(self):
        return False

    def cleanup(self):
        if not self.intro_done:
            self.intro.cleanup()
        self.original.cleanup()

class ChannelContext:
    """Minimal stand-in for commands.Context, for code paths not triggered by a command."""
    def __init__(self, guild, channel):
        self.guild = guild
        self.channel = channel

    async def send(self, *args, **kwargs):
        if self.channel:
            return await self.channel.send(*args, **kwargs)
        logger.warning("No text channel available, dropping message")

"""Help commands: .help and .commands."""
import discord

from ..core import bot

@bot.command(name='commands', aliases=['cmd'])
async def quick_commands(ctx):
    """Quick command reference."""
    embed = discord.Embed(
        title="🎵 Quick Commands",
        description="Essential bot commands at a glance",
        color=0x00ffff
    )
    
    embed.add_field(
        name="**Basic**",
        value="`.play <url>` - Play song\n"
              "`.playlist <url>` - Add playlist (15 songs)\n"
              "`.skip` - Next song\n"
              "`.pause` / `.resume`\n"
              "`.queue` - Show queue\n"
              "`.leave` - Stop & leave",
        inline=True
    )
    
    embed.add_field(
        name="**Settings**",
        value="`.volume <0-100>`\n"
              "`.playnext <url>` - Force a song to play next\n"
              "`.status` - Bot info\n"
              "`.help` - Full help",
        inline=True
    )
    
    embed.set_footer(text="Use .help for detailed explanations")
    await ctx.send(embed=embed)

@bot.command(name='help')
async def help_command(ctx, category: str = None):
    """Show all available commands or specific category help."""
    if category is None:
        # Main help with categories
        embed = discord.Embed(
            title="🎵 HootBot Commands",
            description="Your Discord music bot with advanced features!",
            color=0x00ff00
        )
        
        embed.add_field(
            name="🎶 **Music Commands**",
            value="`.play` / `.p <url or search>` - Play a song or search YouTube\n"
                  "`.playlist` / `.pl <url or artist>` - Add playlist or search for artist songs\n"
                  "`.playnext` / `.pn <url/search/number>` - Play next or jump to queue position\n"
                  "`.skip` / `.next` - Skip current song\n"
                  "`.pause` - Pause playback\n"
                  "`.resume` - Resume playback\n"
                  "`.stop` - Stop, clear queue, and leave\n"
                  "`.restart` - Restart current song\n"
                  "`.nowplaying` / `.np` - Show current song",
            inline=False
        )
        
        embed.add_field(
            name="🎛️ **Queue & Control**",
            value="`.queue` / `.q` - Show current queue\n"
                  "`.shuffle` / `.s` - Shuffle queue (requires 10+ songs)\n"
                  "`.remove <number>` - Remove song from queue\n"
                  "`.join` - Join your voice channel\n"
                  "`.leave` - Leave voice channel\n"
                  "`.volume <0-100>` - Set volume\n"
                  "`.status` - Show bot status",
            inline=False
        )
        
        embed.add_field(
            name="⚙️ **Settings**",
            value="`.debug on/off` - Toggle debug logging",
            inline=False
        )
        
        embed.add_field(
            name="🔧 **Utils**",
            value="`.cleanup <hours>` - Manual cleanup of old downloads\n"
                  "`.checkupdates` - Check if dependencies are up to date\n"
                  "`.skeet` - Friend reference command 😄",
            inline=False
        )
        
        embed.add_field(
            name="📖 **Get Detailed Help**",
            value="`.help music` - Music command details\n"
                  "`.help settings` - Settings explanations\n"
                  "`.help tips` - Usage tips & tricks",
            inline=False
        )
        
        embed.set_footer(text="HootBot • Optimized for speed and reliability")
        await ctx.send(embed=embed)
        
    elif category.lower() == "music":
        embed = discord.Embed(
            title="🎶 Music Commands - Detailed",
            color=0x0099ff
        )
        
        embed.add_field(
            name="`.play` / `.p <url or search>`",
            value="**Play a song from URL or search YouTube**\n"
                  "• Supports YouTube URLs or text search\n"
                  "• Smart filtering: prioritizes official music videos\n"
                  "• Filters out AMVs, fan videos, and non-music content\n"
                  "• Queues if something is already playing",
            inline=False
        )
        
        embed.add_field(
            name="`.playlist` / `.pl <url or artist>`",
            value="**Add multiple songs from playlist or artist search**\n"
                  "• Default: 15 songs (specify number: `.pl artist 20`)\n"
                  "• YouTube playlists, mixes & radio ✅ (YouTube Music links don't work)\n"
                  "• Artist search: finds multiple songs by that artist\n"
                  "• Auto-skips duplicates already in queue",
            inline=False
        )
        
        embed.add_field(
            name="`.playnext` / `.pn <url/search/number>`",
            value="**Insert song next OR jump to queue position**\n"
                  "• With URL/search: adds song to play next\n"
                  "• With number: jumps to that queue position (e.g., `.pn 5`)\n"
                  "• Useful for priority requests or quick navigation",
            inline=False
        )
        
        embed.add_field(
            name="`.skip` / `.next`",
            value="**Skip to next song in queue**\n"
                  "• Stops current playback immediately\n"
                  "• Automatically plays next queued song\n"
                  "• No effect if queue is empty",
            inline=False
        )
        
        embed.add_field(
            name="`.restart`",
            value="**Restart current song from beginning**\n"
                  "• Useful if song started mid-way\n"
                  "• Re-extracts fresh stream data\n"
                  "• Guaranteed to start at 0:00",
            inline=False
        )
        
        embed.add_field(
            name="`.nowplaying` / `.np`",
            value="**Show current track info**\n"
                  "• Displays song title\n"
                  "• Shows who requested it\n"
                  "• Updates in real-time",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    elif category.lower() == "settings":
        embed = discord.Embed(
            title="⚙️ Settings - Detailed",
            color=0xff9900
        )
        
        embed.add_field(
            name="`.debug on/off`",
            value="**Diagnostic Information**\n"
                  "• **ON**: Detailed logs and error info\n"
                  "• **OFF**: Clean, minimal output\n"
                  "• Useful for troubleshooting issues",
            inline=False
        )
        
        embed.add_field(
            name="**Bot Configuration**",
            value="Bot is optimized for speed and reliability with:\n"
                  "• Smart YouTube search with music-only filtering\n"
                  "• Background preloading for instant transitions\n"
                  "• Automatic duplicate detection in playlists\n"
                  "• Cached extraction for faster performance",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    elif category.lower() == "tips":
        embed = discord.Embed(
            title="💡 Tips & Tricks",
            color=0x9900ff
        )
        
        embed.add_field(
            name="🎵 **Getting Best Performance**",
            value="• Bot is automatically optimized for speed\n"
                  "• Background preloading makes transitions instant\n"
                  "• Smart caching reduces repeated extractions\n"
                  "• Join voice channel before using `.play`",
            inline=False
        )
        
        embed.add_field(
            name="🔧 **Troubleshooting**",
            value="• If song starts mid-way: use `.restart`\n"
                  "• If no audio: check `.status` and enable `.debug on`\n"
                  "• Use `.remove <number>` to remove problematic songs\n"
                  "• Use `.pn <number>` to jump to a specific queue position\n"
                  "• Use `.skip` if a song is stuck or not playing",
            inline=False
        )
        
        embed.add_field(
            name="🎶 **URL Support**",
            value="• YouTube videos & playlists ✅\n"
                  "• YouTube Music links ❌ (use the regular youtube.com link)\n"
                  "• Shortened youtu.be links ✅\n"
                  "• Auto-detects playlist vs single video",
            inline=False
        )
        
        embed.add_field(
            name="⚡ **Pro Tips**",
            value="• Queue multiple songs for continuous playback\n"
                  "• Use `.volume` to adjust without re-extraction\n"
                  "• Bot auto-leaves after 30 seconds of inactivity\n"
                  "• `.leave` stops everything and clears queue",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    else:
        await ctx.send(f"Unknown help category: `{category}`\n"
                      f"Available categories: `music`, `settings`, `tips`\n"
                      f"Use `.help` for main command list.")

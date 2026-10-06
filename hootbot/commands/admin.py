"""Maintenance commands, restricted to the bot owner or server admins."""
import asyncio
import logging
import os
import time
from datetime import datetime

import discord

from .. import config
from ..config import logger, DOWNLOAD_FOLDER
from ..core import bot, admin_only
from ..music import music_bot

# ============================================================================
# BOT COMMANDS - File Management
# ============================================================================

@bot.command(name='files')
@admin_only
async def list_files(ctx):
    """List downloaded files from the HootBot downloads folder."""
    try:
        download_dir = DOWNLOAD_FOLDER
        
        # Show the exact path being checked
        await ctx.send(f"📂 **Checking downloads folder:**\n`{download_dir}`\n")
        
        if os.path.exists(download_dir) and os.path.isdir(download_dir):
            files = [f for f in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, f))]
            audio_files = [f for f in files if f.endswith(('.webm', '.mp4', '.mp3', '.m4a'))]
            
            if not audio_files:
                await ctx.send("No audio files in downloads folder.")
                return
            
            # Get file info with timestamps
            file_info = []
            for filename in audio_files[-10:]:  # Show last 10 files
                filepath = os.path.join(download_dir, filename)
                try:
                    file_time = os.path.getmtime(filepath)
                    file_date = datetime.fromtimestamp(file_time).strftime("%m/%d %H:%M")
                    file_size = os.path.getsize(filepath)
                    size_mb = round(file_size / (1024 * 1024), 1)
                    file_info.append(f"🎵 {filename[:50]}{'...' if len(filename) > 50 else ''}\n   📅 {file_date} • 💾 {size_mb}MB")
                except:
                    file_info.append(f"🎵 {filename[:50]}{'...' if len(filename) > 50 else ''}")
            
            msg = f"**Audio files ({len(audio_files)} total):**\n\n" + "\n\n".join(file_info)
            if len(audio_files) > 10:
                msg += f"\n\n... and {len(audio_files) - 10} more files"
            await ctx.send(msg)
        else:
            await ctx.send(f"❌ Downloads folder not found at: `{download_dir}`")
    except Exception as e:
        await ctx.send(f"❌ Error listing files: {e}")
        logger.error(f"Files listing error: {e}")

@bot.command(name='cleanup')
@admin_only
async def manual_cleanup(ctx, hours: int = 24):
    """Manually clean up files older than specified hours from the HootBot downloads folder ONLY."""
    if hours < 1:
        await ctx.send("Hours must be at least 1.")
        return
    
    try:
        current_time = time.time()
        cutoff_time = current_time - (hours * 60 * 60)
        cleaned_count = 0
        
        # Use the absolute path and add safety checks
        download_dir = DOWNLOAD_FOLDER
        
        # Safety verification
        if not (os.path.exists(download_dir) and os.path.isdir(download_dir)):
            await ctx.send(f"❌ Downloads folder not found at: `{download_dir}`")
            return
        
        if not ("HootBot" in download_dir and "downloads" in download_dir):
            await ctx.send(f"❌ Safety check failed: refusing to clean non-HootBot directory")
            return
        
        # Show which directory we're cleaning
        await ctx.send(f"🧹 Cleaning files older than {hours} hours from:\n`{download_dir}`")
        
        for filename in os.listdir(download_dir):
            filepath = os.path.join(download_dir, filename)
            try:
                if os.path.isfile(filepath) and filepath.endswith(('.webm', '.mp4', '.mp3', '.m4a')):
                    file_time = os.path.getmtime(filepath)
                    if file_time < cutoff_time:
                        os.remove(filepath)
                        music_bot.downloaded_files.discard(filepath)
                        cleaned_count += 1
                        logger.info(f"Manual cleanup: removed {filename}")
            except Exception as e:
                logger.error(f"Error cleaning up {filename}: {e}")
        
        if cleaned_count > 0:
            await ctx.send(f"✅ Successfully cleaned up {cleaned_count} audio files older than {hours} hours.")
        else:
            await ctx.send(f"ℹ️ No audio files found older than {hours} hours in downloads folder.")
            
    except Exception as e:
        await ctx.send(f"❌ Error during cleanup: {e}")
        logger.error(f"Manual cleanup error: {e}")

# ============================================================================
# BOT COMMANDS - Settings & Configuration
# ============================================================================

@bot.command(name='debug')
@admin_only
async def toggle_debug(ctx, mode: str = None):
    if mode is None:
        await ctx.send(f"Debug is {'ON' if config.DEBUG else 'OFF'}.")
        return
    
    if mode.lower() in ('on', '1', 'true'):
        config.DEBUG = True
        logging.getLogger().setLevel(logging.DEBUG)
        await ctx.send("Debug enabled.")
    elif mode.lower() in ('off', '0', 'false'):
        config.DEBUG = False
        logging.getLogger().setLevel(logging.INFO)
        await ctx.send("Debug disabled.")
    else:
        await ctx.send("Use 'on' or 'off'.")

# ============================================================================
# BOT COMMANDS - Fun & Miscellaneous
# ============================================================================

@bot.command(name='checkupdates')
@admin_only
async def check_updates(ctx):
    """Check and automatically update outdated dependencies."""
    import subprocess
    import sys
    import re
    
    embed = discord.Embed(
        title="📦 Checking for Updates",
        description="Scanning installed packages and FFmpeg...",
        color=discord.Color.blue()
    )
    
    status_msg = await ctx.send(embed=embed)
    
    try:
        # Check FFmpeg version first
        ffmpeg_version = "Not installed"
        ffmpeg_installed = False
        try:
            ffmpeg_result = await asyncio.to_thread(
                subprocess.run,
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if ffmpeg_result.returncode == 0:
                # Parse version from output (first line usually has version)
                first_line = ffmpeg_result.stdout.split('\n')[0]
                version_match = re.search(r'ffmpeg version ([\d.]+|n[\d.]+)', first_line, re.IGNORECASE)
                if version_match:
                    ffmpeg_version = version_match.group(1)
                    ffmpeg_installed = True
                else:
                    ffmpeg_version = "Installed (version unknown)"
                    ffmpeg_installed = True
        except FileNotFoundError:
            ffmpeg_version = "❌ Not found in PATH"
        except Exception as e:
            ffmpeg_version = f"❌ Error: {str(e)[:50]}"
        
        # Get list of outdated packages
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=json'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            import json
            outdated = json.loads(result.stdout)
            
            if not outdated:
                embed = discord.Embed(
                    title="✅ All Packages Up to Date",
                    description="All installed packages are current!",
                    color=discord.Color.green()
                )
                
                # Show FFmpeg status
                embed.add_field(
                    name="🎬 FFmpeg",
                    value=f"`{ffmpeg_version}`" + ("\n⚠️ Install from: https://ffmpeg.org" if not ffmpeg_installed else ""),
                    inline=False
                )
                
                # Show current versions of core packages
                version_result = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, '-m', 'pip', 'show', 'discord.py', 'yt-dlp', 'PyNaCl'],
                    capture_output=True,
                    text=True
                )
                
                if version_result.returncode == 0:
                    lines = version_result.stdout.split('\n')
                    versions = {}
                    current_pkg = None
                    
                    for line in lines:
                        if line.startswith('Name:'):
                            current_pkg = line.split(':', 1)[1].strip()
                        elif line.startswith('Version:') and current_pkg:
                            versions[current_pkg] = line.split(':', 1)[1].strip()
                            current_pkg = None
                    
                    for pkg, ver in versions.items():
                        embed.add_field(name=pkg, value=f"`{ver}`", inline=True)
                
                await status_msg.edit(embed=embed)
                return
            
            # Updates available - show what will be updated
            embed = discord.Embed(
                title="⚙️ Installing Updates",
                description=f"Found {len(outdated)} package(s) to update...",
                color=discord.Color.orange()
            )
            
            # Show FFmpeg status
            embed.add_field(
                name="🎬 FFmpeg",
                value=f"`{ffmpeg_version}`" + ("\n⚠️ Manual install required from: https://ffmpeg.org" if not ffmpeg_installed else ""),
                inline=False
            )
            
            packages_to_update = []
            for pkg in outdated:
                name = pkg['name']
                current = pkg['version']
                latest = pkg['latest_version']
                packages_to_update.append(name)
                embed.add_field(
                    name=name,
                    value=f"`{current}` → `{latest}`",
                    inline=True
                )
            
            await status_msg.edit(embed=embed)
            
            # Update packages
            update_result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, '-m', 'pip', 'install', '--upgrade'] + packages_to_update,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if update_result.returncode == 0:
                embed = discord.Embed(
                    title="✅ Updates Completed",
                    description=f"Successfully updated {len(packages_to_update)} package(s)!",
                    color=discord.Color.green()
                )
                
                # Check if critical packages were updated
                critical = ['discord.py', 'yt-dlp']
                updated_critical = [p for p in packages_to_update if p.lower() in [c.lower() for c in critical]]
                
                if updated_critical:
                    embed.add_field(
                        name="⚠️ Restart Required",
                        value="Critical packages updated. Please restart the bot for changes to take effect.",
                        inline=False
                    )
                
                embed.set_footer(text=f"Updated: {', '.join(packages_to_update)}")
            else:
                embed = discord.Embed(
                    title="❌ Update Failed",
                    description="Some packages failed to update.",
                    color=discord.Color.red()
                )
                error_msg = update_result.stderr[:1000] if update_result.stderr else "Unknown error"
                embed.add_field(name="Error", value=f"```{error_msg}```", inline=False)
            
            await status_msg.edit(embed=embed)
        else:
            await status_msg.edit(content="❌ Error checking for updates. Make sure pip is working correctly.")
            
    except subprocess.TimeoutExpired:
        await status_msg.edit(content="❌ Update process timed out. Try again later.")
    except Exception as e:
        logger.error(f"Error checking updates: {e}")
        await ctx.send(f"❌ Error checking updates: {str(e)}")

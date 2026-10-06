"""Small helpers used by the commands."""
import re
from urllib.parse import urlparse, parse_qs

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def has_multiple_commands(text):
    """Check for multiple commands in message."""
    if not text:
        return False
    return len(re.findall(r'(?<!\S)\.[A-Za-z]+', text)) > 1

async def reject_multiple_commands(ctx):
    """Reject messages with multiple commands."""
    if has_multiple_commands(getattr(ctx.message, 'content', '')):
        await ctx.send("Please use one command at a time.")
        return True
    return False

def extract_video_id_from_playlist(url):
    """Extract video ID from playlist URL (supports YouTube and YouTube Music)."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get('v', [None])[0]
    except:
        return None

def is_playlist_url(url):
    """Check if URL is a playlist (supports YouTube and YouTube Music)."""
    # Check for standard playlist indicators
    if 'list=' in url or ('playlist' in url and 'watch' in url):
        return True
    # Check for YouTube Music specific URLs
    if 'music.youtube.com' in url.lower() and ('playlist' in url.lower() or 'list=' in url):
        return True
    return False

# ============================================================================
# HootBot - Discord Music Bot
# ============================================================================
# A high-performance Discord music bot with YouTube integration
# Features: Queue management, playlist support, fast playback, auto-cleanup
# ============================================================================

# ============================================================================
# IMPORTS
# ============================================================================
import asyncio
import discord
from discord.ext import commands
import yt_dlp
import re
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from typing import Optional, Dict, Any
import aiohttp
import random
import time
from datetime import datetime, timedelta

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================================
# CONFIGURATION
# ============================================================================

# Debug & Logging
DEBUG = True  # Enable debug logging to diagnose issues

# Performance Settings
IDLE_TIMEOUT = 30  # Seconds before bot leaves due to inactivity
FAST_MODE = True  # Optimize for speed over quality
ULTRA_FAST = True  # Skip all non-essential extraction steps
CACHE_DURATION = 300  # Cache stream URLs for 5 minutes (seconds)

# Download Settings
FORCE_DOWNLOAD = True  # Always download to ensure songs start at 0:00 (slower but reliable)
FORCE_DOWNLOAD_FRAGMENTED = True  # Download fragmented formats to ensure proper start
DOWNLOAD_FOLDER = r"C:\Users\herna\Desktop\HootBot\downloads"

# Audio Settings
Current_volume = 0.1  # Default volume (10%)

# Discord Bot Token
TOKEN = os.environ.get('DISCORD_TOKEN', 'YOUR_TOKEN_HERE')

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
file_handler = RotatingFileHandler('hootsbot.log', maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
logging.getLogger().addHandler(file_handler)
logger = logging.getLogger('hootsbot')

# ============================================================================
# DISCORD BOT SETUP
# ============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class QueueEntry:
    """Represents a song entry in the queue"""
    url: str
    title: str
    requester_id: int
    info: Optional[Dict] = None

# ============================================================================
# MUSIC BOT CLASS
# ============================================================================

class MusicBot:
    """
    Main music bot class that handles:
    - Queue management
    - Audio extraction (yt-dlp)
    - File downloads
    - Caching
    - Cleanup
    """
    def __init__(self):
        self.queue = []
        self.current_track = None
        self.info_cache = {}  # NEW: Cache extracted info by URL
        self.cache_times = {}  # Track when cache entries were added
        self.preload_task = None  # Background task for preloading next song
        
        # Ensure download folder exists
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER)
        
        # Check for cookies file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_path = os.path.join(script_dir, 'cookies.txt')
        has_cookies = os.path.exists(cookies_path)
        
        if has_cookies:
            logger.info(f"✅ Found cookies.txt at: {cookies_path}")
            logger.info("YouTube Premium/Music features enabled!")
        else:
            logger.info(f"ℹ️ No cookies.txt found at: {cookies_path}")
            logger.info("Some YouTube Music content may be restricted")
        
        # Ultra-fast YT-DL options - absolute minimum extraction
        ytdl_fast_opts = {
            'format': 'bestaudio/best/best[ext=m4a]/best[ext=webm]',  # More flexible format selection for YouTube Music
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'no_playlist': True,
            'socket_timeout': 5,
            'retries': 1,
            'extract_flat': False,
            'cachedir': False,
            'no_check_certificate': True,
            'playlist_items': '1',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],  # Use Android client for YouTube Music
                }
            },
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            }
        }
        
        # Add cookies if available
        if has_cookies:
            ytdl_fast_opts['cookiefile'] = cookies_path
        
        self.ytdl_fast = yt_dlp.YoutubeDL(ytdl_fast_opts)
        
        # Standard options (only used for problematic videos as fallback)
        ytdl_opts = {
            'format': 'bestaudio/best/best[ext=m4a]/best[ext=webm]',  # More flexible format selection
            'quiet': True,
            'no_warnings': True,
            'extractaudio': True,
            'audioformat': 'best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s-%(id)s.%(ext)s',
            'socket_timeout': 10,
            'retries': 2,
            'fragment_retries': 2,
            'ignore_errors': False,
            'cachedir': False,
            'no_check_certificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                }
            },
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            }
        }
        
        # Add cookies if available
        if has_cookies:
            ytdl_opts['cookiefile'] = cookies_path
        
        self.ytdl = yt_dlp.YoutubeDL(ytdl_opts)
        self.downloaded_files = set()
        self.locks = {}
        self.timeout_tasks = {}
        self.cleanup_task = None
        self.timeout_tasks = {}
        self.cleanup_task = None  # Will be started when bot is ready
        
    async def start_cleanup_task(self):
        """Start the cleanup task when bot is ready."""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self.cleanup_old_files())
        
    def get_ffmpeg_options(self, is_file=False):
        if is_file:
            # Options for local files - NO seeking, just play naturally from start
            opts = {
                'before_options': '-nostdin',
                'options': '-vn -hide_banner -loglevel info'  # Always verbose for debugging
            }
        else:
            # Options for streaming
            opts = {
                'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2',
                'options': '-vn -hide_banner -loglevel info -bufsize 64k'  # Always verbose
            }
        return opts
    
    async def extract_info(self, url):
        """Extract video information."""
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            if info:
                # Simple SABR detection
                formats = info.get('formats', [])
                with_url = sum(1 for f in formats if f and f.get('url'))
                info['_needs_download'] = len(formats) > 0 and with_url * 3 < len(formats)
                logger.info(f'Extracted {url}: {len(formats)} formats, {with_url} with URLs')
            return info
        except Exception as e:
            logger.error(f'Extraction failed for {url}: {e}')
            return None
    
    async def extract_info_fast(self, url, use_cache=True):
        """Ultra-fast extraction with caching - optimized for instant playback."""
        # Check cache first
        if use_cache and url in self.info_cache:
            cache_age = time.time() - self.cache_times.get(url, 0)
            if cache_age < CACHE_DURATION:
                logger.info(f'Using cached info for {url} (age: {int(cache_age)}s)')
                return self.info_cache[url]
            else:
                # Expired cache
                del self.info_cache[url]
                del self.cache_times[url]
        
        try:
            loop = asyncio.get_event_loop()
            # Use ultra-fast ytdl instance
            info = await loop.run_in_executor(
                None, 
                lambda: self.ytdl_fast.extract_info(url, download=False)
            )
            
            if info:
                # Cache it
                self.info_cache[url] = info
                self.cache_times[url] = time.time()
                logger.info(f'Fast extraction complete for: {info.get("title", "Unknown")}')
            return info
        except Exception as e:
            error_msg = str(e).lower()
            # Check for common unavailability errors
            if 'unavailable' in error_msg or 'not available' in error_msg or 'private' in error_msg:
                logger.warning(f'Video unavailable, skipping: {url}')
                return None  # Don't try fallback for unavailable videos
            logger.error(f'Fast extraction failed for {url}: {e}')
            # Fallback to standard extraction for other errors
            return await self.extract_info(url)
    
    def select_format(self, info):
        """Select best audio format optimized for speed."""
        formats = info.get('formats', [])
        if not formats:
            return None, False
        
        # Find best audio format prioritizing speed
        best = None
        best_score = -1
        
        for f in formats:
            if not f or not f.get('url') or f.get('acodec') in (None, 'none'):
                continue
            
            # Prefer non-fragmented formats
            is_fragmented = bool(f.get('fragments') or f.get('fragment_base_url') or 
                               (f.get('protocol', '') in ('m3u8', 'dash')))
            
            # Check for formats that might not start at beginning
            has_seek_issues = bool(f.get('fragment_base_url') or 
                                 f.get('protocol') == 'dash' or
                                 'live' in str(f.get('format_note', '')).lower())
            
            # Prefer formats that start faster
            is_fast_format = bool(f.get('protocol') in ('https', 'http') and 
                                not f.get('fragments'))
            
            score = f.get('abr', 0) or f.get('tbr', 0)
            if not is_fragmented:
                score += 1000  # Heavily prefer progressive
            if not has_seek_issues:
                score += 500   # Prefer formats without seek issues
            if is_fast_format:
                score += 200   # Prefer fast-loading formats
            
            # Slightly prefer lower bitrates for faster streaming (under 160kbps)
            if score > 0 and score <= 160:
                score += 50
            
            if score > best_score:
                best_score = score
                best = f
        
        if best:
            is_frag = bool(best.get('fragments') or best.get('fragment_base_url') or 
                          (best.get('protocol', '') in ('m3u8', 'dash')))
            return best.get('url'), is_frag
        
        return None, False
    
    async def download_audio(self, url, title="Unknown"):
        """Download audio for reliable playback from 0:00."""
        try:
            logger.info(f"Starting download for: {title} from {url}")
            loop = asyncio.get_event_loop()
            
            # Download with full extraction
            download_info = await loop.run_in_executor(
                None, lambda: self.ytdl.extract_info(url, download=True)
            )
            
            if not download_info:
                logger.error(f"No download info returned for {title}")
                return None, None
            
            # Get the filename
            filename = self.ytdl.prepare_filename(download_info)
            logger.info(f"Expected filename: {filename}")
            
            # Wait a moment for file to be fully written
            await asyncio.sleep(0.2)
            
            if not filename:
                logger.error(f"No filename generated for {title}")
                return None, None
            
            if not os.path.exists(filename):
                logger.error(f"File not found after download: {filename}")
                # Check if there's a similar file (sometimes extension differs)
                dirname = os.path.dirname(filename)
                basename = os.path.splitext(os.path.basename(filename))[0]
                if os.path.exists(dirname):
                    similar_files = [f for f in os.listdir(dirname) if basename in f]
                    if similar_files:
                        actual_file = os.path.join(dirname, similar_files[0])
                        logger.info(f"Found similar file: {actual_file}")
                        filename = actual_file
                    else:
                        logger.error(f"No similar files found in {dirname}")
                        return None, None
                else:
                    return None, None
            
            abs_path = os.path.abspath(filename)
            file_size = os.path.getsize(abs_path)
            logger.info(f"Download successful: {abs_path} ({file_size} bytes)")
            
            if file_size < 1000:
                logger.error(f"Downloaded file too small ({file_size} bytes), likely corrupt")
                return None, None
            
            self.downloaded_files.add(abs_path)
            return abs_path, download_info
            
        except Exception as e:
            logger.error(f'Download failed for {url}: {e}', exc_info=True)
            # Check for specific error types
            error_str = str(e).lower()
            if '403' in error_str or 'forbidden' in error_str:
                logger.error("HTTP 403 Forbidden - YouTube may be blocking yt-dlp. Consider updating: pip install -U yt-dlp")
        return None, None
    
    async def preload_next_song(self):
        """Preload the next song in the background to reduce transition time."""
        try:
            if not self.queue or len(self.queue) == 0:
                return
            
            next_entry = self.queue[0]
            
            # Skip if already has cached info
            if next_entry.info:
                logger.info(f"Next song already has cached info: {next_entry.title}")
                return
            
            logger.info(f"🔄 Preloading next song in background: {next_entry.title}")
            
            # Extract info
            if ULTRA_FAST:
                next_entry.info = await self.extract_info_fast(next_entry.url)
            else:
                next_entry.info = await self.extract_info(next_entry.url)
            
            if not next_entry.info:
                logger.warning(f"Failed to preload info for: {next_entry.title}")
                return
            
            # If FORCE_DOWNLOAD is enabled, also predownload the file
            if FORCE_DOWNLOAD:
                logger.info(f"📥 Pre-downloading: {next_entry.title}")
                filepath, _ = await self.download_audio(next_entry.url, next_entry.title)
                if filepath:
                    logger.info(f"✅ Pre-downloaded ready: {next_entry.title}")
                else:
                    logger.warning(f"Pre-download failed for: {next_entry.title}")
            else:
                logger.info(f"✅ Preload complete: {next_entry.title}")
                
        except Exception as e:
            logger.error(f"Error preloading next song: {e}")
    
    def correct_artist_spelling(self, query):
        """Correct common misspellings of artist names."""
        # Dictionary of common misspellings -> correct spelling
        corrections = {
            'chappel roan': 'chappell roan',
            'chapel roan': 'chappell roan',
            'chapell roan': 'chappell roan',
            'billy eilish': 'billie eilish',
            'bille eilish': 'billie eilish',
            'taylor swift': 'taylor swift',
            'arianna grande': 'ariana grande',
            'ariana grand': 'ariana grande',
            'dua lipa': 'dua lipa',
            'olivia rodrigo': 'olivia rodrigo',
            'olivia rodrigues': 'olivia rodrigo',
            'sabrina carpenter': 'sabrina carpenter',
            'sabrina carpener': 'sabrina carpenter',
            'doja cat': 'doja cat',
            'dojacat': 'doja cat',
            'sza': 'sza',
            's z a': 'sza',
        }
        
        query_lower = query.lower()
        for misspelling, correct in corrections.items():
            if misspelling in query_lower:
                corrected = query_lower.replace(misspelling, correct)
                logger.info(f"Corrected spelling: '{query}' -> '{corrected}'")
                return corrected
        
        return query
    
    async def search_youtube(self, query, max_results=1):
        """Search YouTube and return video URLs, filtering out concerts, shorts, and live streams."""
        try:
            # Correct common artist name misspellings
            query = self.correct_artist_spelling(query)
            
            logger.info(f"Searching YouTube for: {query}")
            loop = asyncio.get_event_loop()
            
            # Use yt-dlp to search YouTube
            search_opts = {
                'format': 'bestaudio/best/best[ext=m4a]/best[ext=webm]',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # Just get URLs, don't extract full info
                'skip_download': True,
                'default_search': 'ytsearch',
            }
            
            # Add cookies if available
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cookies_path = os.path.join(script_dir, 'cookies.txt')
            if os.path.exists(cookies_path):
                search_opts['cookiefile'] = cookies_path
            
            search_ytdl = yt_dlp.YoutubeDL(search_opts)
            
            # Search for more results than needed so we can filter out unwanted content
            # Hint to YouTube to prefer VEVO/Topic, then we'll strictly filter
            search_query = f"ytsearch{max_results * 15}:{query} official"  # Get 15x results to filter
            
            info = await loop.run_in_executor(
                None,
                lambda: search_ytdl.extract_info(search_query, download=False)
            )
            
            if not info or 'entries' not in info:
                logger.warning(f"No results found for: {query}")
                return []
            
            logger.info(f"YouTube returned {len(info['entries'])} results for: {query}")
            
            # Filter out unwanted content and prioritize official music
            filtered_results = []
            seen_songs = set()  # Track unique song titles
            
            import re
            
            def normalize_title(title):
                """Extract core song title for deduplication."""
                # Convert to lowercase first
                title = title.lower()
                # Remove everything in parentheses and brackets
                title = re.sub(r'\([^)]*\)', '', title)
                title = re.sub(r'\[[^\]]*\]', '', title)
                # Remove common words that don't affect song identity
                remove_words = ['official', 'music', 'video', 'audio', 'lyric', 'lyrics']
                for word in remove_words:
                    title = title.replace(word, '')
                # Remove common separators and extra info - take last part (song title)
                parts = re.split(r'[-–—|]', title)
                # Usually format is "Artist - Song Title", so take the last significant part
                title = parts[-1] if len(parts) > 1 else parts[0]
                # Remove extra whitespace
                title = ' '.join(title.split())
                return title
            
            for entry in info['entries']:
                if entry:
                    video_id = entry.get('id')
                    original_title = entry.get('title', 'Unknown')
                    uploader = entry.get('uploader', '').lower()
                    channel = entry.get('channel', '').lower()
                    duration = entry.get('duration', 0)
                    
                    # Accept VEVO, Topic, or artist's own official channel
                    is_vevo = 'vevo' in uploader or 'vevo' in channel
                    is_topic = 'topic' in uploader or 'topic' in channel or '- topic' in channel
                    
                    # Extract artist name from query
                    artist_query = query.lower()
                    for word in ['official', 'music', 'video', 'audio', 'vevo', 'topic', 'song']:
                        artist_query = artist_query.replace(word, '')
                    artist_query = ' '.join(artist_query.split())
                    
                    # Check if channel name matches artist name with stricter matching
                    is_artist_channel = False
                    if artist_query:
                        channel_text = (uploader + ' ' + channel).lower()
                        
                        # Method 1: Check if full artist name appears in channel (best match)
                        if artist_query in channel_text:
                            is_artist_channel = True
                            logger.debug(f"  ✓ Exact artist match: '{artist_query}' in '{channel_text[:50]}'")
                        else:
                            # Method 2: For multi-word artists, require high word overlap
                            query_words = [word for word in artist_query.split() if len(word) > 3]
                            if query_words:
                                words_in_channel = sum(1 for word in query_words if word in channel_text)
                                match_percentage = words_in_channel / len(query_words) if query_words else 0
                                
                                # Stricter: require 75% match for multi-word artists (was 50%)
                                # Single word artists need exact match
                                if len(query_words) == 1:
                                    # Single word: must match exactly (but allow in middle of channel name)
                                    is_artist_channel = query_words[0] in channel_text
                                else:
                                    # Multi-word: need 75%+ match to prevent "Ruby Darkrose" → "Rubi Rose"
                                    is_artist_channel = match_percentage >= 0.75
                                    
                                if is_artist_channel:
                                    logger.debug(f"  ✓ Partial artist match: {words_in_channel}/{len(query_words)} words ({match_percentage:.0%})")
                                else:
                                    logger.debug(f"  ✗ Weak artist match: {words_in_channel}/{len(query_words)} words ({match_percentage:.0%}) in '{channel_text[:50]}'")
                    
                    # Check if this is a song title match (query words appear in video title)
                    title_lower = original_title.lower()
                    title_match = False
                    if artist_query:
                        query_words = [word for word in artist_query.split() if len(word) > 3]
                        words_in_title = sum(1 for word in query_words if word in title_lower)
                        # If 60%+ of search words appear in title, it's likely the right song
                        if query_words and words_in_title >= len(query_words) * 0.6:
                            title_match = True
                    
                    # Accept video if it meets one of these criteria:
                    # 1. VEVO or Topic channel (highly trusted)
                    # 2. Artist channel match (channel name matches search)
                    # 3. Strong title match (80%+ words) - accept even without official indicators
                    # 4. Good title match (60%+) + has official indicators
                    has_official_indicators = any(indicator in title_lower for indicator in ['official', 'lyric', 'lyrics', 'audio'])
                    
                    # Calculate title match strength for filtering decision
                    strong_title_match_for_filter = False
                    if artist_query:
                        query_words = [word for word in artist_query.split() if len(word) > 3]
                        if query_words:
                            words_in_title = sum(1 for word in query_words if word in title_lower)
                            match_ratio = words_in_title / len(query_words)
                            # Strong match: 80%+ of search words in title
                            strong_title_match_for_filter = match_ratio >= 0.8
                    
                    # Accept if: trusted channel OR artist match OR strong title match OR (good title match + official)
                    if not (is_vevo or is_topic or is_artist_channel or strong_title_match_for_filter or (title_match and has_official_indicators)):
                        logger.debug(f"Filtered out (not relevant): {original_title[:50]} (channel: {uploader})")
                        continue
                    
                    channel_type = 'VEVO' if is_vevo else ('Topic' if is_topic else ('Artist' if is_artist_channel else 'Other'))
                    logger.info(f"Found {channel_type} result: {original_title[:50]}... (duration: {duration}s)")
                    

                    
                    # Basic sanity checks
                    if duration and (duration < 60 or duration > 600):
                        logger.info(f"❌ Filtered out: {original_title[:50]} (duration: {duration}s - must be 60-600s)")
                        continue
                    
                    # Filter out promotional/announcement videos (not actual songs)
                    title_lower = original_title.lower()
                    
                    # Reject videos with hashtags unless it's clearly a song (artist - title format)
                    if '#' in original_title:
                        if ' - ' not in original_title:
                            logger.debug(f"Filtered out: {original_title} (hashtags without song format)")
                            continue
                    
                    # Reject obvious non-songs and non-music content
                    non_song_phrases = [
                        'if you liked', 'if you like', 'just you wait', 
                        'coming soon', 'announcement', 'teaser', 'snippet', 'preview',
                        'new album', 'new ep', 'out now', 'available now',
                        'listen to', 'check out', 'stream now',
                        'tv series', 'tv show', 'episode', 'season', 'trailer',
                        'movie', 'film', 'soundtrack', 'ost', 'theme song',
                        'adaptation', 'anime', 'drama', 'netflix', 'hbo',
                        'scene from', 'clip from', 'full movie', 'full episode',
                        ' amv ', 'amv|', '|amv', 'anime music video',
                        'fan made', 'fanmade', 'fan video', 'mmd', 'animation'
                    ]
                    rejected_phrase = next((phrase for phrase in non_song_phrases if phrase in title_lower), None)
                    if rejected_phrase:
                        logger.info(f"❌ Filtered out: {original_title[:50]} (contains '{rejected_phrase}')")
                        continue
                    
                    # For artist channels, require proper song format (Artist - Title) or standard music video keywords
                    # BUT be lenient if the title matches the search query well
                    if is_artist_channel and not is_vevo and not is_topic:
                        has_proper_format = ' - ' in original_title or '"' in original_title
                        has_music_keywords = any(keyword in title_lower for keyword in ['official music video', 'official video', 'official audio', 'lyrics', 'lyric'])
                        
                        # Allow if strong title match (50%+ query words in title)
                        strong_title_match = False
                        if artist_query:
                            query_words = [word for word in artist_query.split() if len(word) > 3]
                            if query_words:
                                words_in_title = sum(1 for word in query_words if word in title_lower)
                                strong_title_match = words_in_title >= len(query_words) * 0.5
                        
                        if not (has_proper_format or has_music_keywords or strong_title_match):
                            logger.info(f"❌ Filtered out: {original_title[:50]} (artist channel but no proper song format)")
                            continue
                    
                    # Score: Start with channel type base score
                    score = 100 if is_vevo else 90
                    
                    # CRITICAL: Title matching (most important for finding the right song)
                    # Use original query, not just artist_query
                    original_query_lower = query.lower()
                    for word in ['official', 'music', 'video', 'audio', 'vevo', 'topic', 'song']:
                        original_query_lower = original_query_lower.replace(word, '')
                    original_query_lower = ' '.join(original_query_lower.split())
                    
                    query_words = [word for word in original_query_lower.split() if len(word) > 2]
                    title_words_list = title_lower.split()
                    
                    # Count exact word matches
                    matching_words = sum(1 for word in query_words if word in title_words_list)
                    
                    # Calculate match percentage
                    if query_words:
                        match_percentage = matching_words / len(query_words)
                        
                        # HUGE boost for near-perfect matches
                        if match_percentage >= 0.9:  # 90%+ match
                            score += 200
                            logger.info(f"  ⭐ EXCELLENT match: {matching_words}/{len(query_words)} words")
                        elif match_percentage >= 0.7:  # 70-89% match
                            score += 100
                            logger.info(f"  ✓ Good match: {matching_words}/{len(query_words)} words")
                        elif match_percentage >= 0.5:  # 50-69% match
                            score += 50
                            logger.debug(f"  ~ Partial match: {matching_words}/{len(query_words)} words")
                    
                    # HUGE boost if artist name appears in BOTH channel AND title
                    # This helps ensure we get the right artist (e.g., "Ruby Darkrose" in both places)
                    if is_artist_channel and artist_query:
                        # Check if artist appears in title too
                        artist_in_title = artist_query in title_lower
                        if artist_in_title:
                            score += 150
                            logger.info(f"  ⭐⭐ Artist in channel AND title bonus (+150)")
                    
                    # Extra boost for official music video indicators
                    music_indicators = ['official music video', 'official video', 'official audio', 'official lyric']
                    if any(keyword in title_lower for keyword in music_indicators):
                        score += 100
                        logger.debug(f"  + Official content bonus (+100)")
                    
                    # Strong boost for lyric videos (usually the original song)
                    if 'lyric' in title_lower or 'lyrics' in title_lower:
                        score += 80
                        logger.debug(f"  + Lyric video bonus (+80)")
                    
                    # Boost for music-specific terms
                    if any(term in title_lower for term in ['music', 'song', 'audio', 'single']):
                        score += 20
                    
                    # PENALIZE non-music content that slipped through
                    non_music_terms = ['tv', 'series', 'episode', 'trailer', 'movie', 'film', 'clip', 'scene', 'adaptation']
                    if any(term in title_lower for term in non_music_terms):
                        score -= 100
                        logger.debug(f"  - Non-music penalty")
                    
                    if video_id:
                        # Check for duplicate songs
                        normalized = normalize_title(entry.get('title', 'Unknown'))
                        if normalized in seen_songs:
                            logger.debug(f"Filtered out: {entry.get('title', 'Unknown')} (duplicate song)")
                            continue
                        
                        seen_songs.add(normalized)
                        url = f"https://www.youtube.com/watch?v={video_id}"
                        filtered_results.append({
                            'url': url, 
                            'title': entry.get('title', 'Unknown'),
                            'duration': duration,
                            'score': score
                        })
                        logger.info(f"Found: {entry.get('title', 'Unknown')} ({duration}s, score: {score}) - {url}")
                    
                    # Stop when we have enough filtered results
                    if len(filtered_results) >= max_results * 2:
                        break
            
            # Sort by score (highest first) to prioritize best matches
            filtered_results.sort(key=lambda x: x['score'], reverse=True)
            
            # For single song searches (!play), take the best match
            # For playlists, shuffle for variety to avoid repetition
            if max_results == 1:
                return filtered_results[:1]
            else:
                # For playlists: shuffle top results to avoid always playing the same first song
                import random
                
                # Take top results (twice what we need to ensure quality)
                top_pool = filtered_results[:max_results * 2]
                
                # Shuffle them all to get variety
                random.shuffle(top_pool)
                
                return top_pool[:max_results]
            
        except Exception as e:
            logger.error(f"YouTube search failed for '{query}': {e}", exc_info=True)
            return []
    
    def normalize_title_for_comparison(self, title):
        """Normalize title for duplicate detection."""
        import re
        title = title.lower()
        # Remove everything in parentheses and brackets
        title = re.sub(r'\([^)]*\)', '', title)
        title = re.sub(r'\[[^\]]*\]', '', title)
        # Remove common words that don't affect song identity
        remove_words = ['official', 'music', 'video', 'audio', 'lyric', 'lyrics', 'hd', 'hq', 'remaster', 'remastered']
        for word in remove_words:
            title = title.replace(word, '')
        # Remove common separators and extra info - take last part (song title)
        parts = re.split(r'[-–—|]', title)
        # Usually format is "Artist - Song Title", so take the last significant part
        title = parts[-1] if len(parts) > 1 else parts[0]
        # Remove extra whitespace
        title = ' '.join(title.split())
        return title
    
    def is_duplicate_in_queue(self, title):
        """Check if a song with similar title is already in queue."""
        normalized_new = self.normalize_title_for_comparison(title)
        for entry in self.queue:
            normalized_existing = self.normalize_title_for_comparison(entry.title)
            if normalized_new == normalized_existing:
                return True
        return False
    
    def add_to_queue(self, url, title, requester_id):
        """Add entry to queue."""
        entry = QueueEntry(url=url, title=title, requester_id=requester_id)
        self.queue.append(entry)
        return entry
    
    async def extract_playlist(self, url, max_items=10):
        """Extract multiple videos from a playlist/radio URL."""
        try:
            is_music_youtube = 'music.youtube.com' in url
            logger.info(f"Extracting playlist from: {url} (YouTube Music: {is_music_youtube})")
            loop = asyncio.get_event_loop()
            
            # Check if it's a YouTube Mix/Radio (RDEM, RDMM, etc.)
            is_radio = 'list=RD' in url or 'list=RDEM' in url or 'list=RDMM' in url
            
            # Keep YouTube Music URLs as-is (don't convert to regular YouTube)
            # With cookies, yt-dlp can handle music.youtube.com directly
            if is_music_youtube:
                logger.info("Keeping YouTube Music URL (cookies enabled)")
            
            # Check for cookies file
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cookies_path = os.path.join(script_dir, 'cookies.txt')
            has_cookies = os.path.exists(cookies_path)
            
            # Use a playlist-specific yt-dlp instance
            ytdl_opts = {
                'format': 'bestaudio/best/best[ext=m4a]/best[ext=webm]',  # Flexible format for YouTube Music
                'quiet': not DEBUG,  # Show output in debug mode
                'no_warnings': not DEBUG,
                'playliststart': 1,  # Start from the first item
                'playlistend': max_items,  # Limit to first N items
                'socket_timeout': 15,  # Longer timeout for radio playlists
                'retries': 3,
                'cachedir': False,
                'no_check_certificate': True,
                'ignoreerrors': True,  # Continue on errors
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],  # Use Android client to avoid JS runtime issues
                        'skip': ['hls', 'dash']  # Skip problematic formats
                    }
                },
                # Add headers to bypass 403 errors
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate',
                }
            }
            
            # Add cookies if available for premium content
            if has_cookies:
                ytdl_opts['cookiefile'] = cookies_path
                logger.info("Using cookies for playlist extraction (Premium features enabled)")
            
            # For radio/mix playlists, don't use flat extraction
            # For regular playlists (including YouTube Music), use flat extraction (faster)
            if is_radio:
                logger.info("Detected YouTube Radio/Mix - using full extraction")
                ytdl_opts['extract_flat'] = False
            else:
                logger.info("Regular playlist - using fast flat extraction")
                ytdl_opts['extract_flat'] = 'in_playlist'
                # When using flat extraction, we need to process entries differently
                ytdl_opts['lazy_playlist'] = False
            
            ytdl_playlist = yt_dlp.YoutubeDL(ytdl_opts)
            
            info = await loop.run_in_executor(
                None,
                lambda: ytdl_playlist.extract_info(url, download=False)
            )
            
            if not info:
                logger.warning("No info returned from playlist extraction")
                return []
            
            # Handle both playlist and single video results
            entries = []
            if 'entries' in info:
                # It's a playlist
                logger.info(f"Processing playlist with {len(info.get('entries', []))} total entries")
                for i, entry in enumerate(info['entries']):
                    if not entry:
                        logger.debug(f"Skipping None entry at index {i}")
                        continue
                    
                    if len(entries) >= max_items:
                        break
                    
                    # Try multiple ways to get the video ID/URL
                    video_id = entry.get('id') or entry.get('video_id')
                    if not video_id:
                        logger.warning(f"Entry {i} has no video ID, skipping: {entry}")
                        continue
                    
                    # Construct proper YouTube URL - preserve YouTube Music if that's the source
                    video_url = entry.get('webpage_url') or entry.get('url')
                    if not video_url or not video_url.startswith('http'):
                        # Build URL from video ID - use YouTube Music if playlist is from YouTube Music
                        if is_music_youtube:
                            video_url = f"https://music.youtube.com/watch?v={video_id}"
                        else:
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    title = entry.get('title') or entry.get('name') or f'Unknown (ID: {video_id})'
                    
                    entries.append({'url': video_url, 'title': title})
                    logger.debug(f"Added entry {len(entries)}: {title}")
                    
            else:
                # Single video - treat as playlist with 1 item
                video_url = info.get('webpage_url') or info.get('url')
                title = info.get('title', 'Unknown')
                if video_url:
                    entries.append({'url': video_url, 'title': title})
                    logger.debug(f"Added single video: {title}")
            
            logger.info(f"Successfully extracted {len(entries)} entries from playlist")
            return entries
            
        except Exception as e:
            logger.error(f'Playlist extraction failed for {url}: {e}', exc_info=True)
            return []
    
    def get_queue_display(self):
        """Get formatted queue display."""
        if not self.queue:
            return "The queue is currently empty."
        
        queue_length = len(self.queue)
        # Discord message limit is 2000 characters, so we need to paginate for large queues
        if queue_length <= 20:
            # Show all songs for small queues
            items = [f"{i+1}. {entry.title}" for i, entry in enumerate(self.queue)]
            return f"**Current Queue ({queue_length} songs):**\n" + "\n".join(items)
        else:
            # For large queues, show first 15 and last 5
            items = [f"{i+1}. {entry.title}" for i, entry in enumerate(self.queue[:15])]
            items.append(f"\n... {queue_length - 20} more songs ...\n")
            items.extend([f"{i+1}. {entry.title}" for i, entry in enumerate(self.queue[-5:], start=queue_length-4)])
            return f"**Current Queue ({queue_length} songs total):**\n" + "\n".join(items)
    
    def clear_queue(self):
        """Clear queue and return count."""
        count = len(self.queue)
        self.queue.clear()
        self.current_track = None
        return count
    
    async def get_guild_lock(self, guild_id):
        """Get per-guild async lock."""
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        return self.locks[guild_id]
    
    async def cleanup_file(self, filepath):
        """Remove downloaded file."""
        try:
            def _remove():
                if os.path.exists(filepath):
                    os.remove(filepath)
            await asyncio.get_event_loop().run_in_executor(None, _remove)
            self.downloaded_files.discard(filepath)
        except:
            pass
    
    async def cleanup_old_files(self):
        """Clean up files older than 24 hours every hour - RESTRICTED to downloads folder only."""
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                current_time = time.time()
                cutoff_time = current_time - (24 * 60 * 60)  # 24 hours ago
                
                # Safety check: only clean the specific downloads directory
                download_dir = DOWNLOAD_FOLDER
                if os.path.exists(download_dir) and os.path.isdir(download_dir):
                    # Verify this is our downloads directory
                    if "HootBot" in download_dir and "downloads" in download_dir:
                        for filename in os.listdir(download_dir):
                            filepath = os.path.join(download_dir, filename)
                            try:
                                if os.path.isfile(filepath) and filepath.endswith(('.webm', '.mp4', '.mp3', '.m4a')):
                                    file_time = os.path.getmtime(filepath)
                                    if file_time < cutoff_time:
                                        os.remove(filepath)
                                        self.downloaded_files.discard(filepath)
                                        logger.info(f"Auto-cleaned old file: {filename} from {download_dir}")
                            except Exception as e:
                                logger.error(f"Error cleaning up {filename}: {e}")
                    else:
                        logger.error(f"Safety check failed: unexpected download directory {download_dir}")
            except Exception as e:
                logger.error(f"Error in cleanup routine: {e}")
    
    def create_after_callback(self, ctx, filepath=None):
        """Create a safe after callback for voice playback."""
        def after_callback(error):
            try:
                # Use call_soon_threadsafe to schedule the coroutine from any thread
                loop = bot.loop
                if loop and not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        playback_finished(ctx, error, filepath), 
                        loop
                    )
                else:
                    logger.error("Bot event loop not available for after callback")
            except Exception as e:
                logger.error(f"Error in after callback: {e}")
        return after_callback

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================
music_bot = MusicBot()

# ============================================================================
# HELPER CLASSES
# ============================================================================

class YTDLSource(discord.PCMVolumeTransformer):
    """Audio source wrapper for discord.py with volume control"""
    def __init__(self, source, *, data=None):
        super().__init__(source, volume=Current_volume)
        self.data = data or {}
        self.title = self.data.get('title', 'Unknown')

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def has_multiple_commands(text):
    """Check for multiple commands in message."""
    if not text:
        return False
    return len(re.findall(r'(?<!\S)![A-Za-z]+', text)) > 1

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

# ============================================================================
# PLAYBACK FUNCTIONS
# ============================================================================

async def play_audio(ctx, entry):
    """Play audio for a queue entry - optimized for instant playback."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        logger.error(f"No voice client for {entry.title}")
        return False
    
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
            
            # Download silently
            filepath, download_info = await music_bot.download_audio(entry.url, entry.title)
            
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
            
            try:
                source = YTDLSource(
                    discord.FFmpegPCMAudio(filepath, **music_bot.get_ffmpeg_options(is_file=True)),
                    data=download_info
                )
                voice_client.play(source, after=music_bot.create_after_callback(ctx, filepath))
                await ctx.send(f"🎵 {entry.title}")
                logger.info(f"Successfully started playback of downloaded file: {entry.title}")
                
                # Start preloading next song in background
                if music_bot.queue:
                    asyncio.create_task(music_bot.preload_next_song())
                
                return True
            except Exception as play_error:
                logger.error(f"Failed to play downloaded file {filepath}: {play_error}", exc_info=True)
                await ctx.send(f"❌ Failed to play downloaded file for **{entry.title}**")
                return False
        
        # Stream directly (fast path - only if download not needed)
        if stream_url:
            logger.info(f"Streaming from URL: {entry.title}")
            try:
                source = YTDLSource(
                    discord.FFmpegPCMAudio(stream_url, **music_bot.get_ffmpeg_options(is_file=False)),
                    data=entry.info
                )
                voice_client.play(source, after=music_bot.create_after_callback(ctx))
                await ctx.send(f"🎵 {entry.title}")
                logger.info(f"Successfully started playback: {entry.title}")
                
                # Start preloading next song in background
                if music_bot.queue:
                    asyncio.create_task(music_bot.preload_next_song())
                
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
        
        # Play outside the lock to avoid deadlock
        success = await play_audio(ctx, entry)
        
        if success:
            if failed_songs:
                logger.info(f"Successfully playing after skipping {len(failed_songs)} unavailable songs")
            return  # Successfully playing, exit
        
        # Failed to play - track it and continue
        failed_songs.append(entry.title)
        logger.warning(f"Failed to play {entry.title}, total failed: {len(failed_songs)}")
        
        # Only send message every 5 songs to avoid spam
        if len(failed_songs) % 5 == 1:
            await ctx.send(f"⏭️ Skipping unavailable songs... ({len(failed_songs)} skipped so far)")
        
        await asyncio.sleep(0.3)  # Small delay to avoid hammering
        # Continue loop to try next song

async def handle_idle(ctx):
    """Handle idle timeout."""
    await asyncio.sleep(IDLE_TIMEOUT)
    voice_client = ctx.guild.voice_client
    if voice_client and not voice_client.is_playing() and not music_bot.queue:
        # Random subtle messages
        import random
        messages = [
            "Leaving due to inactivity. Someone should consider portion control. 🍔",
            "Leaving due to inactivity. The gym membership is still waiting... 💪",
            "Leaving due to inactivity. Moderation is key, they say. 🍰",
            "Leaving due to inactivity. Maybe skip seconds next time? 🍕",
            "Leaving due to inactivity. Salad: it exists. 🥗",
            "Leaving due to inactivity. The treadmill misses you. 🏃",
            "Leaving due to inactivity. Someone's been hitting the buffet hard. 🍽️",
            "Leaving due to inactivity. Those pants aren't going to fit themselves. 👖",
            "Leaving due to inactivity. The elevator thanks you for your business. 🛗",
            "Leaving due to inactivity. Remember: sharing is caring. Especially dessert. 🧁"
        ]
        await ctx.send(random.choice(messages))
        await leave_voice(ctx)

async def leave_voice(ctx):
    """Leave voice channel and cleanup."""
    voice_client = ctx.guild.voice_client
    if not voice_client:
        return
    
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    count = music_bot.clear_queue()
    
    # Cancel timeout
    guild_id = ctx.guild.id
    if guild_id in music_bot.timeout_tasks:
        music_bot.timeout_tasks[guild_id].cancel()
        del music_bot.timeout_tasks[guild_id]
    
    await voice_client.disconnect()
    return count

# ============================================================================
# BOT COMMANDS - Voice Control
# ============================================================================

@bot.command(name='join')
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send(f'{ctx.author.name} is not connected to a voice channel.')
        return
    
    await ctx.author.voice.channel.connect()
    
    # Set volume
    vc = ctx.guild.voice_client
    if vc and hasattr(vc, 'source') and vc.source:
        vc.source.volume = Current_volume

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
    
    # Handle playlist URLs - extract specific video
    if is_playlist_url(url):
        video_id = extract_video_id_from_playlist(url)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Ultra-fast extraction - get full info immediately and cache it
    if ULTRA_FAST:
        info = await music_bot.extract_info_fast(url)
        if not info:
            await ctx.send("❌ Could not extract information.")
            return
        title = info.get('title', 'Unknown')
        # Create entry with cached info for instant playback
        entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)
    else:
        # Fallback to old method
        if FAST_MODE:
            try:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: music_bot.ytdl.extract_info(url, download=False, process=False))
                title = info.get('title', 'Unknown') if info else 'Unknown'
                entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id)
            except:
                title = 'Unknown'
                entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id)
        else:
            info = await music_bot.extract_info(url)
            if not info:
                await ctx.send("Could not extract information.")
                return
            title = info.get('title', 'Unknown')
            entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)
    
    music_bot.queue.append(entry)
    
    if DEBUG:
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
    if ULTRA_FAST:
        info = await music_bot.extract_info_fast(url)
        if not info:
            await ctx.send("❌ Could not extract information.")
            return
        title = info.get('title', 'Unknown')
        entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)
    else:
        # Fallback
        if FAST_MODE:
            try:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: music_bot.ytdl.extract_info(url, download=False, process=False))
                title = info.get('title', 'Unknown') if info else 'Unknown'
                entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id)
            except:
                title = 'Unknown'
                entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id)
        else:
            info = await music_bot.extract_info(url)
            if not info:
                await ctx.send("Could not extract information.")
                return
            title = info.get('title', 'Unknown')
            entry = QueueEntry(url=url, title=title, requester_id=ctx.author.id, info=info)

    # Insert next (front of queue)
    music_bot.queue.insert(0, entry)

    if DEBUG:
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
            max_songs = 50  # Default 50 for playlist URLs (get more songs automatically)
        else:
            max_songs = 10  # Default 10 for artist searches (more conservative)
    
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
        
        # Search with extra results to account for duplicates (fetch 4x what we need)
        # Higher multiplier helps ensure we get enough good results after filtering
        results = await music_bot.search_youtube(url, max_results=target_songs * 4)
        
        if not results:
            await ctx.send(f"❌ No results found for: **{url}**")
            return
        
        # Add search results to queue, skipping duplicates until we reach target
        added_count = 0
        skipped_duplicates = 0
        for result in results:
            # Stop if we've reached our target
            if added_count >= target_songs:
                break
            
            try:
                # Check for duplicates before adding
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
            except Exception as e:
                logger.error(f"Failed to queue search result: {e}")
                continue
        
        if added_count == 0:
            if skipped_duplicates > 0:
                await ctx.send(f"❌ All {skipped_duplicates} songs were already in the queue.")
            else:
                await ctx.send("❌ Could not add any songs to the queue.")
            return
        
        # Show summary message
        message = f"✅ Added **{added_count}** song(s)"
        if skipped_duplicates > 0:
            message += f" ({skipped_duplicates} duplicate(s) skipped)"
        await ctx.send(message)
        
        # Start playback if idle (but not if paused)
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next(ctx)
        
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
        except Exception as e:
            logger.error(f"Failed to queue entry: {e}")
            continue
    
    if added_count == 0:
        if skipped_duplicates > 0:
            await ctx.send(f"❌ All {skipped_duplicates} songs were already in the queue.")
        else:
            await ctx.send("❌ Could not add songs")
        return
    
    # Show summary message
    message = f"✅ Added **{added_count}** song(s)"
    if skipped_duplicates > 0:
        message += f" ({skipped_duplicates} duplicate(s) skipped)"
    await ctx.send(message)
    
    # Start playback immediately if idle (but not if paused)
    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(ctx)



# ============================================================================
# BOT COMMANDS - Queue Management
# ============================================================================

@bot.command(name='queue', aliases=['q'])
async def show_queue(ctx):
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
        await ctx.send("❌ Invalid position! Use a number like: `!remove 5`")
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
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await ctx.send("Not connected to a voice channel.")
        return
    
    # Clear the queue
    queue_count = len(music_bot.queue)
    music_bot.queue.clear()
    
    # Stop playback
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    
    # Leave voice channel
    await voice_client.disconnect()
    
    if queue_count > 0:
        await ctx.send(f"⏹️ Stopped playback, cleared {queue_count} song(s), and left voice channel.")
    else:
        await ctx.send("⏹️ Stopped playback and left voice channel.")

@bot.command(name='volume')
async def volume(ctx, value: int):
    if not 0 <= value <= 100:
        await ctx.send("Volume must be between 0-100.")
        return
    
    global Current_volume
    Current_volume = value / 100.0
    
    voice_client = ctx.guild.voice_client
    if voice_client and hasattr(voice_client, 'source') and voice_client.source:
        voice_client.source.volume = Current_volume
    
    await ctx.send(f"Volume set to {value}%.")

# ============================================================================
# BOT COMMANDS - File Management
# ============================================================================

@bot.command(name='files')
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

# @bot.command(name='fastmode')
# async def toggle_fast_mode(ctx, mode: str = None):
#     """Toggle fast mode for quicker streaming."""
#     global FAST_MODE
#     if mode is None:
#         await ctx.send(f"Fast mode is {'ON' if FAST_MODE else 'OFF'}.")
#         return
#     
#     if mode.lower() in ('on', '1', 'true'):
#         FAST_MODE = True
#         await ctx.send("Fast mode enabled. Prioritizing speed over extraction quality.")
#     elif mode.lower() in ('off', '0', 'false'):
#         FAST_MODE = False
#         await ctx.send("Fast mode disabled. Full extraction enabled.")
#     else:
#         await ctx.send("Use 'on' or 'off'.")

# @bot.command(name='forcedownload')
# async def toggle_force_download(ctx, mode: str = None):
#     """Toggle force download mode to fix timing issues."""
#     global FORCE_DOWNLOAD
#     if mode is None:
#         await ctx.send(f"Force download is {'ON' if FORCE_DOWNLOAD else 'OFF'}.")
#         return
#     
#     if mode.lower() in ('on', '1', 'true'):
#         FORCE_DOWNLOAD = True
#         await ctx.send("Force download enabled. All tracks will be downloaded for proper timing.")
#     elif mode.lower() in ('off', '0', 'false'):
#         FORCE_DOWNLOAD = False
#         await ctx.send("Force download disabled. Will try streaming when possible.")
#     else:
#         await ctx.send("Use 'on' or 'off'.")

@bot.command(name='debug')
async def toggle_debug(ctx, mode: str = None):
    global DEBUG
    if mode is None:
        await ctx.send(f"Debug is {'ON' if DEBUG else 'OFF'}.")
        return
    
    if mode.lower() in ('on', '1', 'true'):
        DEBUG = True
        logging.getLogger().setLevel(logging.DEBUG)
        await ctx.send("Debug enabled.")
    elif mode.lower() in ('off', '0', 'false'):
        DEBUG = False
        logging.getLogger().setLevel(logging.INFO)
        await ctx.send("Debug disabled.")
    else:
        await ctx.send("Use 'on' or 'off'.")

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

# @bot.command(name='finduser')
# async def find_user(ctx, *, search_term: str = "skeet"):
#     """Debug command to find users by partial name match."""
#     if not DEBUG:
#         await ctx.send("Enable debug mode first with `!debug on`")
#         return
#     
#     matches = []
#     search_lower = search_term.lower()
#     
#     for member in ctx.guild.members:
#         if (search_lower in member.name.lower() or 
#             search_lower in member.display_name.lower()):
#             matches.append(f"**{member.name}** (display: {member.display_name}, id: {member.id})")
#     
#     if matches:
#         await ctx.send(f"Found {len(matches)} matches for '{search_term}':\n" + "\n".join(matches[:10]))
#     else:
#         await ctx.send(f"No matches found for '{search_term}'")

# @bot.command(name='testping')
# async def test_ping(ctx, user_id: int = None):
#     """Test ping by user ID (for debugging)."""
#     if not DEBUG:
#         await ctx.send("Enable debug mode first with `!debug on`")
#         return
#     
#     if user_id:
#         try:
#             user = bot.get_user(user_id) or ctx.guild.get_member(user_id)
#             if user:
#                 await ctx.send(f"Test ping: {user.mention}")
#             else:
#                 await ctx.send(f"User with ID {user_id} not found")
#         except:
#             await ctx.send(f"Invalid user ID: {user_id}")
#     else:
#         await ctx.send("Usage: `!testping <user_id>` - Use `!finduser` to get user IDs")

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
        value="`!play <url>` - Play song\n"
              "`!playlist <url>` - Add playlist (10 songs)\n"
              "`!skip` - Next song\n"
              "`!pause` / `!resume`\n"
              "`!queue` - Show queue\n"
              "`!leave` - Stop & leave",
        inline=True
    )
    
    embed.add_field(
        name="**Settings**",
        value="`!volume <0-100>`\n"
              "`!fastmode on/off`\n"
              "`!forcedownload on/off`\n"
              "`!playnext <url>` - Force a song to play next\n"
              "`!status` - Bot info\n"
              "`!help` - Full help",
        inline=True
    )
    
    embed.set_footer(text="Use !help for detailed explanations")
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
            value="`!play` / `!p <url or search>` - Play a song or search YouTube\n"
                  "`!playlist` / `!pl <url or artist>` - Add playlist or search for artist songs\n"
                  "`!playnext` / `!pn <url/search/number>` - Play next or jump to queue position\n"
                  "`!skip` / `!next` - Skip current song\n"
                  "`!pause` - Pause playback\n"
                  "`!resume` - Resume playback\n"
                  "`!stop` - Stop, clear queue, and leave\n"
                  "`!restart` - Restart current song\n"
                  "`!nowplaying` / `!np` - Show current song",
            inline=False
        )
        
        embed.add_field(
            name="🎛️ **Queue & Control**",
            value="`!queue` / `!q` - Show current queue\n"
                  "`!shuffle` / `!s` - Shuffle queue (requires 10+ songs)\n"
                  "`!remove <number>` - Remove song from queue\n"
                  "`!join` - Join your voice channel\n"
                  "`!leave` - Leave voice channel\n"
                  "`!volume <0-100>` - Set volume\n"
                  "`!status` - Show bot status",
            inline=False
        )
        
        embed.add_field(
            name="⚙️ **Settings**",
            value="`!debug on/off` - Toggle debug logging",
            inline=False
        )
        
        embed.add_field(
            name="🔧 **Utils**",
            value="`!cleanup <hours>` - Manual cleanup of old downloads\n"
                  "`!skeet` - Friend reference command 😄",
            inline=False
        )
        
        embed.add_field(
            name="📖 **Get Detailed Help**",
            value="`!help music` - Music command details\n"
                  "`!help settings` - Settings explanations\n"
                  "`!help tips` - Usage tips & tricks",
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
            name="`!play` / `!p <url or search>`",
            value="**Play a song from URL or search YouTube**\n"
                  "• Supports YouTube URLs or text search\n"
                  "• Smart filtering: prioritizes official music videos\n"
                  "• Filters out AMVs, fan videos, and non-music content\n"
                  "• Queues if something is already playing",
            inline=False
        )
        
        embed.add_field(
            name="`!playlist` / `!pl <url or artist>`",
            value="**Add multiple songs from playlist or artist search**\n"
                  "• Default: 10 songs (specify number: `!pl artist 20`)\n"
                  "• YouTube playlists, mixes, radio, & YouTube Music albums ✅\n"
                  "• Artist search: finds multiple songs by that artist\n"
                  "• Auto-skips duplicates already in queue",
            inline=False
        )
        
        embed.add_field(
            name="`!playnext` / `!pn <url/search/number>`",
            value="**Insert song next OR jump to queue position**\n"
                  "• With URL/search: adds song to play next\n"
                  "• With number: jumps to that queue position (e.g., `!pn 5`)\n"
                  "• Useful for priority requests or quick navigation",
            inline=False
        )
        
        embed.add_field(
            name="`!skip` / `!next`",
            value="**Skip to next song in queue**\n"
                  "• Stops current playback immediately\n"
                  "• Automatically plays next queued song\n"
                  "• No effect if queue is empty",
            inline=False
        )
        
        embed.add_field(
            name="`!restart`",
            value="**Restart current song from beginning**\n"
                  "• Useful if song started mid-way\n"
                  "• Re-extracts fresh stream data\n"
                  "• Guaranteed to start at 0:00",
            inline=False
        )
        
        embed.add_field(
            name="`!nowplaying` / `!np`",
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
            name="`!debug on/off`",
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
                  "• Join voice channel before using `!play`",
            inline=False
        )
        
        embed.add_field(
            name="🔧 **Troubleshooting**",
            value="• If song starts mid-way: use `!restart`\n"
                  "• If no audio: check `!status` and enable `!debug on`\n"
                  "• Use `!remove <number>` to remove problematic songs\n"
                  "• Use `!pn <number>` to jump to a specific queue position\n"
                  "• Use `!skip` if a song is stuck or not playing",
            inline=False
        )
        
        embed.add_field(
            name="🎶 **URL Support**",
            value="• YouTube videos & playlists ✅\n"
                  "• YouTube Music (songs, albums, playlists) ✅\n"
                  "• Shortened youtu.be links ✅\n"
                  "• Auto-detects playlist vs single video",
            inline=False
        )
        
        embed.add_field(
            name="⚡ **Pro Tips**",
            value="• Queue multiple songs for continuous playback\n"
                  "• Use `!volume` to adjust without re-extraction\n"
                  "• Bot auto-leaves after 30 seconds of inactivity\n"
                  "• `!leave` stops everything and clears queue",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    else:
        await ctx.send(f"Unknown help category: `{category}`\n"
                      f"Available categories: `music`, `settings`, `tips`\n"
                      f"Use `!help` for main command list.")

# ============================================================================
# BOT COMMANDS - Fun & Miscellaneous
# ============================================================================

@bot.command(name='skeet')
async def skeet(ctx):
    """Send a random cat fact with a cute cat image and ping skeetanese."""
    # Try to find the specific user by ID first (more reliable)
    target_user = bot.get_user(209039208294121472) or ctx.guild.get_member(209039208294121472)
    
    # Fallback to name search if ID lookup fails
    if not target_user:
        search_names = ["skeetanese", "skeet"]
        
        if DEBUG:
            logger.info(f"Searching for user in guild with {len(ctx.guild.members)} members")
        
        for member in ctx.guild.members:
            member_display = member.display_name.lower()
            member_username = member.name.lower()
            
            for search_name in search_names:
                if (search_name in member_display or search_name in member_username or
                    member_display == search_name or member_username == search_name):
                    target_user = member
                    if DEBUG:
                        logger.info(f"Found user: {member.name} (display: {member.display_name}, id: {member.id})")
                    break
            
            if target_user:
                break
    
    # Get a random cat fact and image
    cat_fact = await get_random_cat_fact()
    cat_image_url = await get_random_cat_image()
    
    # 25% chance for a playful insult
    insult = ""
    if random.randint(1, 4) == 1:  # 1 in 4 chance
        playful_insults = [
            "You magnificent weirdo! 🙄",
            "Hope you're not too busy being fabulous! 💅",
            "Time to take a break from being a goofball! 🤪",
            "Stop being so extra for 5 minutes! 😏",
            "You absolute legend (and pain in my circuits)! 🤖"
        ]
        insult = f" {random.choice(playful_insults)}"
    
    # Create embed with cat image
    embed = discord.Embed(
        title="🐱 Cat Fact Time!",
        description=cat_fact,
        color=0xFF69B4  # Hot pink color
    )
    
    if cat_image_url:
        embed.set_image(url=cat_image_url)
    
    embed.set_footer(text="Powered by adorable cats 🐾")
    
    # Send message WITHOUT pinging the user. Use display name or plain text instead.
    if target_user:
        display_name = getattr(target_user, 'display_name', None) or getattr(target_user, 'name', 'skeetanese')
        mention_text = f"{display_name}{insult} Here's your daily dose of cat wisdom! (no ping)"
    else:
        # Use plain text fallback (no mention)
        mention_text = f"Hey skeetanese{insult} Here's your daily dose of cat wisdom!"

    # Send embed with content (no mentions)
    await ctx.send(content=mention_text, embed=embed)

# ============================================================================
# HELPER FUNCTIONS - Cat Facts & Images
# ============================================================================

async def get_random_cat_fact():
    """Fetch a random cat fact from an API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://catfact.ninja/fact') as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('fact', 'Cats are amazing creatures!')
                else:
                    return await get_fallback_cat_fact()
    except:
        return await get_fallback_cat_fact()

async def get_fallback_cat_fact():
    """Return a random cat fact from a local list if API fails."""
    fallback_facts = [
        "Cats have over 20 muscles that control their ears.",
        "A group of cats is called a 'clowder'.",
        "Cats can't taste sweetness.",
        "A cat's purr vibrates at a frequency that promotes bone healing.",
        "Cats sleep for 12 to 16 hours a day.",
        "A cat has 32 muscles in each ear.",
        "Cats have a third eyelid called a 'nictitating membrane'.",
        "A cat's brain is biologically more similar to a human brain than it is to a dog's.",
        "Cats can run up to 30 mph.",
        "A cat's whiskers are roughly as wide as its body."
    ]
    return random.choice(fallback_facts)

async def get_random_cat_image():
    """Fetch a random cute cat image from APIs."""
    # Try multiple cat image APIs for reliability
    image_apis = [
        'https://api.thecatapi.com/v1/images/search',
        'https://cataas.com/cat?json=true',
        'https://aws.random.cat/meow'
    ]
    
    for api_url in image_apis:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Handle different API response formats
                        if api_url.startswith('https://api.thecatapi.com'):
                            if data and len(data) > 0:
                                return data[0].get('url')
                        elif api_url.startswith('https://cataas.com'):
                            if data and 'url' in data:
                                return f"https://cataas.com{data['url']}"
                        elif api_url.startswith('https://aws.random.cat'):
                            if data and 'file' in data:
                                return data['file']
        except Exception as e:
            logger.debug(f"Cat image API {api_url} failed: {e}")
            continue
    
    # If all APIs fail, return a fallback image URL
    fallback_images = [
        "https://cataas.com/cat",
        "https://placekitten.com/400/300",
        "https://loremflickr.com/400/300/cat"
    ]
    return random.choice(fallback_images)

# ============================================================================
# BOT EVENTS
# ============================================================================

@bot.event
async def on_ready():
    """Called when bot is ready and connected"""
    logger.info(f'Bot ready: {bot.user}')
    print(f'Logged in as {bot.user}')
    
    # Start cleanup task
    await music_bot.start_cleanup_task()
    logger.info("Started file cleanup task")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    print('Starting HootBot...')
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f'Bot failed to start: {e}')
        logger.error(f'Startup failed: {e}')
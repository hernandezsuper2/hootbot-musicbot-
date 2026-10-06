"""MusicBot: YouTube search, extraction, downloads, caching and the queue."""
import asyncio
import copy
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional, Dict

import yt_dlp

from . import config
from .config import (logger, BASE_DIR, ULTRA_FAST, CACHE_DURATION, INFO_REUSE_MAX_AGE,
                     FORCE_DOWNLOAD, DOWNLOAD_FOLDER)
from .core import bot

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
    filepath: Optional[str] = None  # Cached download path from preload

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
        script_dir = str(BASE_DIR)  # the HootBot folder (this file is one level down, in hootbot/)
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
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'socket_timeout': 5,
            'retries': 1,
            'extract_flat': False,
            'cachedir': False,
            'playlist_items': '1',
            'js_runtimes': {'node': {}},
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            }
        }

        # No cookies for ytdl_fast: when cookies are present, YouTube requires PO tokens
        # even for the iOS client, which needs a JS runtime we don't have.
        # Anonymous iOS requests bypass PO token requirements entirely.
        # Also: don't force player_client=android_vr — that client's https formats now
        # require a GVS PO Token we can't provide, so yt-dlp drops most of them (~5 left
        # vs ~41 with default client selection), which is what caused the 403/"unavailable"
        # errors. Let yt-dlp pick clients itself; js_runtimes=node lets it use the
        # Node.js already installed on the server instead of the missing default (deno).

        self.ytdl_fast = yt_dlp.YoutubeDL(ytdl_fast_opts)
        
        # Standard options (only used for problematic videos as fallback)
        ytdl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
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
            'js_runtimes': {'node': {}},
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            }
        }

        # No cookies for ytdl (download/fallback): same PO token reason as ytdl_fast.
        # iOS client works anonymously; quality difference (128 vs 256kbps) is acceptable.

        self.ytdl = yt_dlp.YoutubeDL(ytdl_opts)
        
        # Pre-built YoutubeDL for search queries (reused across all search_youtube calls)
        ytdl_search_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,   # Just get metadata, no full extraction
            'skip_download': True,
            'default_search': 'ytsearch',
        }
        if has_cookies:
            ytdl_search_opts['cookiefile'] = cookies_path
        self.ytdl_search = yt_dlp.YoutubeDL(ytdl_search_opts)
        
        self.downloaded_files = set()
        self.locks = {}
        self.timeout_tasks = {}     # Per-guild idle-timeout tasks
        self.play_next_running = set()  # Per-guild guard against concurrent play_next loops
        self.reconnect_tasks = {}   # Per-guild voice reconnect tasks
        self.last_text_channel = {} # Per-guild last text channel (for reconnect messages)
        self.cleanup_task = None    # Started when bot is ready
        self.is_extracting_playlist = False  # Flag to track playlist extraction
        self.welcome_enabled = {}   # Per-guild welcome sound toggle (default: enabled)
        self.last_playlist_url = None    # URL of the last loaded playlist
        self.last_playlist_offset = 0   # How many songs have been loaded from it so far
        
    async def start_cleanup_task(self):
        """Start the cleanup task when bot is ready."""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self.cleanup_old_files())
        
    def get_ffmpeg_options(self, is_file=False):
        loglevel = 'info' if config.DEBUG else 'error'
        if is_file:
            # Options for local files - NO seeking, just play naturally from start
            opts = {
                'before_options': '-nostdin',
                'options': f'-vn -hide_banner -loglevel {loglevel}'
            }
        else:
            # Options for streaming - 512k buffer reduces audio dropouts vs old 64k
            opts = {
                'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2',
                'options': f'-vn -hide_banner -loglevel {loglevel} -bufsize 512k'
            }
        return opts
    
    async def extract_info(self, url):
        """Extract video information."""
        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            if info:
                # Check if this is a live stream
                if info.get('is_live') or info.get('live_status') == 'is_live':
                    logger.warning(f'Detected live stream, rejecting: {url}')
                    return None
                # Simple SABR detection
                formats = info.get('formats', [])
                with_url = sum(1 for f in formats if f and f.get('url'))
                info['_needs_download'] = len(formats) > 0 and with_url * 3 < len(formats)
                info['_extracted_at'] = time.time()
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
            loop = asyncio.get_running_loop()
            # Use ultra-fast ytdl instance
            info = await loop.run_in_executor(
                None, 
                lambda: self.ytdl_fast.extract_info(url, download=False)
            )
            
            if info:
                # Check if this is a live stream
                if info.get('is_live') or info.get('live_status') == 'is_live':
                    logger.warning(f'Detected live stream, rejecting: {url}')
                    return None
                info['_extracted_at'] = time.time()
                # Cache it
                self.prune_info_cache()
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
    
    def prune_info_cache(self, max_entries=200):
        """Drop expired entries, and the oldest ones beyond max_entries, so memory doesn't grow forever."""
        now = time.time()
        for url in [u for u, t in self.cache_times.items() if now - t >= CACHE_DURATION]:
            self.info_cache.pop(url, None)
            self.cache_times.pop(url, None)
        if len(self.info_cache) >= max_entries:
            for url in sorted(self.cache_times, key=self.cache_times.get)[:len(self.info_cache) - max_entries + 1]:
                self.info_cache.pop(url, None)
                self.cache_times.pop(url, None)

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
    
    async def download_audio(self, url, title="Unknown", info=None):
        """Download audio for reliable playback from 0:00.

        If recently extracted info is passed in, download from it directly instead of
        extracting the video a second time (saves ~1s per song).
        """
        try:
            logger.info(f"Starting download for: {title} from {url}")
            loop = asyncio.get_running_loop()
            
            download_info = None
            if info and time.time() - info.get('_extracted_at', 0) < INFO_REUSE_MAX_AGE:
                try:
                    info_copy = copy.deepcopy(info)  # yt-dlp mutates the dict; keep the cached one clean
                    download_info = await loop.run_in_executor(
                        None, lambda: self.ytdl.process_ie_result(info_copy, download=True)
                    )
                except Exception as e:
                    logger.warning(f"Download from cached info failed for {title}, re-extracting: {e}")
                    download_info = None

            if not download_info:
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
                filepath, _ = await self.download_audio(next_entry.url, next_entry.title, next_entry.info)
                if filepath:
                    next_entry.filepath = filepath  # Cache so play_audio skips re-download
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
            'arianna grande': 'ariana grande',
            'ariana grand': 'ariana grande',
            'olivia rodrigues': 'olivia rodrigo',
            'sabrina carpener': 'sabrina carpenter',
            'dojacat': 'doja cat',
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
            loop = asyncio.get_running_loop()
            
            # Fetch 6x more results than needed for filtering; cap at 60 to avoid huge requests
            fetch_count = min(max_results * 6, 60)
            search_query = f"ytsearch{fetch_count}:{query} official"
            
            info = await loop.run_in_executor(
                None,
                lambda: self.ytdl_search.extract_info(search_query, download=False)
            )
            
            if not info or 'entries' not in info:
                logger.warning(f"No results found for: {query}")
                return []
            
            logger.info(f"YouTube returned {len(info['entries'])} results for: {query}")
            
            # Filter out unwanted content and prioritize official music
            filtered_results = []
            seen_songs = set()  # Track unique song titles
            
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
                    query_words = [word for word in artist_query.split() if len(word) > 3]

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
                        normalized = self.normalize_title_for_comparison(entry.get('title', 'Unknown'))
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
                # Take top results (twice what we need to ensure quality)
                top_pool = filtered_results[:max_results * 2]
                
                # Shuffle them all to get variety
                random.shuffle(top_pool)
                
                return top_pool[:max_results]
            
        except Exception as e:
            logger.error(f"YouTube search failed for '{query}': {e}", exc_info=True)
            return []
    
    def normalize_title_for_comparison(self, title):
        """Normalize title for duplicate detection.

        Handles the common YouTube title format: "Artist - Song Title | Album/Playlist"
        The album suffix is stripped FIRST so different songs from the same album don't
        all normalize to the album name and get spuriously flagged as duplicates.
        """
        title = title.lower()
        # Strip album/playlist label that appears after '|' BEFORE any other processing.
        # e.g. "Artist - Song | Album Name" -> "Artist - Song"
        if '|' in title:
            title = title.split('|')[0]
        # Remove everything in parentheses and brackets (e.g. "(Video Oficial)", "[HD]")
        title = re.sub(r'\([^)]*\)', '', title)
        title = re.sub(r'\[[^\]]*\]', '', title)
        # Remove common filler words that don't affect song identity
        remove_words = ['official', 'music', 'video', 'audio', 'lyric', 'lyrics', 'hd', 'hq', 'remaster', 'remastered']
        for word in remove_words:
            title = title.replace(word, '')
        # Split by artist-title separator (dash variants) and keep the song title part.
        # Format is usually "Artist - Song Title", so take the last meaningful segment.
        parts = re.split(r'[-\u2013\u2014]', title)
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
    
    async def extract_playlist(self, url, max_items=15, start=1):
        """Extract multiple videos from a playlist/radio URL."""
        self.is_extracting_playlist = True  # Set flag when starting extraction
        try:
            is_music_youtube = 'music.youtube.com' in url
            logger.info(f"Extracting playlist from: {url} (YouTube Music: {is_music_youtube}, start={start})")
            loop = asyncio.get_running_loop()

            # Check if it's a YouTube Mix/Radio (RDEM, RDMM, etc.)
            is_radio = 'list=RD' in url or 'list=RDEM' in url or 'list=RDMM' in url
            
            # Keep YouTube Music URLs as-is (don't convert to regular YouTube)
            # With cookies, yt-dlp can handle music.youtube.com directly
            if is_music_youtube:
                logger.info("Keeping YouTube Music URL (cookies enabled)")
            
            # Check for cookies file
            script_dir = str(BASE_DIR)  # the HootBot folder (this file is one level down, in hootbot/)
            cookies_path = os.path.join(script_dir, 'cookies.txt')
            has_cookies = os.path.exists(cookies_path)
            
            # Use a playlist-specific yt-dlp instance
            ytdl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
                'quiet': not config.DEBUG,  # Show output in debug mode
                'no_warnings': not config.DEBUG,
                'playliststart': start,
                'playlistend': start + max_items - 1,
                'socket_timeout': 15,  # Longer timeout for radio playlists
                'retries': 3,
                'cachedir': False,
                'ignoreerrors': True,  # Continue on errors
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
            
            # Always use flat extraction - we only need URL and title from each entry.
            # Audio format URLs are resolved lazily at play time via extract_info_fast,
            # so full extraction here is unnecessary and causes JS challenge failures.
            if is_radio:
                logger.info("Detected YouTube Radio/Mix - using flat extraction")
            else:
                logger.info("Regular playlist - using flat extraction")
            ytdl_opts['extract_flat'] = 'in_playlist'
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
        finally:
            self.is_extracting_playlist = False  # Clear flag when extraction completes
    
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
            await asyncio.get_running_loop().run_in_executor(None, _remove)
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
            from .playback import playback_finished  # imported here: playback imports this module
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

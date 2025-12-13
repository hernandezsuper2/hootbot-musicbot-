# audio_manager.py - Audio extraction and playback logic
import asyncio
import yt_dlp
import discord
import threading
import os
from pathlib import Path
from config import get_ffmpeg_options, DEBUG, FORCE_DOWNLOAD_FRAGMENTS

class AudioManager:
    def __init__(self, logger):
        self.logger = logger
        self.ytdl = yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True})
        self.downloaded_files = set()
        
    async def extract_info(self, url):
        """Extract video info with SABR detection."""
        if not url:
            return None
            
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            if info:
                self._detect_sabr(info)
                self.logger.info(f'Extracted: {url} - formats: {len(info.get("formats", []))}')
                return info
        except Exception as e:
            self.logger.error(f'Extraction failed for {url}: {e}')
            return None
    
    def _detect_sabr(self, info):
        """Detect SABR/nsig issues and mark info."""
        formats = info.get('formats', [])
        total = len(formats)
        with_url = sum(1 for f in formats if f and f.get('url'))
        fragmented = sum(1 for f in formats if self._is_fragmented(f))
        
        sabr = False
        if total > 0:
            if with_url == 0 or with_url * 4 < total or fragmented == total:
                sabr = True
        
        info['_sabr_affected'] = sabr
        info['_stats'] = {'total': total, 'with_url': with_url, 'fragmented': fragmented}
    
    def _is_fragmented(self, format_dict):
        """Check if format is fragmented."""
        if not format_dict:
            return False
        if format_dict.get('fragment_base_url') or format_dict.get('fragments'):
            return True
        protocol = (format_dict.get('protocol') or '').lower()
        return protocol in ('m3u8', 'm3u8_native', 'dash', 'f4m', 'ism')
    
    def select_best_format(self, info):
        """Select best audio format with preference for progressive streams."""
        formats = info.get('formats', [])
        if not formats:
            return None, None, False
        
        # Prefer non-fragmented https formats
        best = None
        best_score = -1
        
        for f in formats:
            if not f or not f.get('url') or f.get('acodec') in (None, 'none'):
                continue
                
            is_frag = self._is_fragmented(f)
            protocol = (f.get('protocol') or '').lower()
            
            # Score: higher for non-fragmented, https protocol
            score = f.get('abr', 0) or f.get('tbr', 0) or 0
            if not is_frag:
                score += 1000  # Heavily prefer non-fragmented
            if protocol in ('https', 'http'):
                score += 100
                
            if score > best_score:
                best_score = score
                best = f
        
        if best:
            return best.get('url'), best, self._is_fragmented(best)
        return None, None, False
    
    async def download_and_prepare(self, url, title="Unknown"):
        """Download audio file for local playback."""
        try:
            download_info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.ytdl.extract_info(url, download=True)
            )
            filename = self.ytdl.prepare_filename(download_info)
            if filename and os.path.exists(filename):
                abs_path = os.path.abspath(filename)
                self.downloaded_files.add(abs_path)
                return abs_path, download_info
        except Exception as e:
            self.logger.error(f'Download failed for {url}: {e}')
        return None, None
    
    def create_audio_source(self, source_path_or_url, info=None):
        """Create Discord audio source."""
        return YTDLSource(
            discord.FFmpegPCMAudio(source_path_or_url, **get_ffmpeg_options(DEBUG)),
            data=info
        )
    
    async def cleanup_file(self, filepath):
        """Remove downloaded file."""
        try:
            def _remove():
                if os.path.exists(filepath):
                    os.remove(filepath)
            await asyncio.get_event_loop().run_in_executor(None, _remove)
            self.downloaded_files.discard(filepath)
        except Exception:
            pass

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data=None):
        from config import Current_volume
        super().__init__(source, volume=Current_volume)
        self.data = data or {}
        self.title = self.data.get('title') if isinstance(self.data, dict) else None

# queue_manager.py - Queue and playback state management
import asyncio
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class QueueEntry:
    url: str
    title: str
    requester_id: int
    info: Optional[Dict[Any, Any]] = None
    stream_url: Optional[str] = None
    is_fragmented: bool = False
    sabr_affected: bool = False

class QueueManager:
    def __init__(self, logger):
        self.logger = logger
        self.queue: List[QueueEntry] = []
        self.current_track: Optional[QueueEntry] = None
        self.locks: Dict[int, asyncio.Lock] = {}
        self.retry_scheduled: set = set()
        self.retry_lock = threading.Lock()
        
    def add_entry(self, url: str, title: str, requester_id: int) -> QueueEntry:
        """Add new entry to queue."""
        entry = QueueEntry(url=url, title=title, requester_id=requester_id)
        self.queue.append(entry)
        return entry
    
    def get_next_entry(self) -> Optional[QueueEntry]:
        """Get and remove next entry from queue."""
        return self.queue.pop(0) if self.queue else None
    
    def clear_queue(self):
        """Clear all entries from queue."""
        count = len(self.queue)
        self.queue.clear()
        self.current_track = None
        return count
    
    def get_queue_display(self) -> str:
        """Get formatted queue for display."""
        if not self.queue:
            return "The queue is currently empty."
        
        items = [f"{i+1}. {entry.title or entry.url}" 
                for i, entry in enumerate(self.queue)]
        return "**Current Queue:**\n" + "\n".join(items)
    
    async def get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        """Get per-guild lock for queue operations."""
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        return self.locks[guild_id]
    
    def set_retry_scheduled(self, guild_id: int):
        """Mark guild as having retry scheduled."""
        with self.retry_lock:
            self.retry_scheduled.add(guild_id)
    
    def clear_retry_scheduled(self, guild_id: int):
        """Clear retry scheduled marker."""
        with self.retry_lock:
            self.retry_scheduled.discard(guild_id)
    
    def is_retry_scheduled(self, guild_id: int) -> bool:
        """Check if retry is scheduled for guild."""
        with self.retry_lock:
            return guild_id in self.retry_scheduled

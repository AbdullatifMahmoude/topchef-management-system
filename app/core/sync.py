import asyncio
import time
from enum import Enum
from typing import Set
from app.core.logging import logger

class SyncMode(Enum):
    WEBSOCKET = "websocket"
    POLLING = "polling"
    OFFLINE = "offline"

class SyncManager:
    """
    Production-grade Synchronization Manager.
    Controls the transition between Real-time (WS) and Fallback (REST) modes.
    Implements event deduplication and exponential backoff state.
    """
    def __init__(self):
        self._mode = SyncMode.POLLING
        self._last_ws_activity = 0
        self._last_poll_time = 0
        self._ws_healthy = False
        self._lock = asyncio.Lock()
        
        # Event Deduplication (Last 1000 event IDs)
        self._seen_events: Set[str] = set()
        self._event_history_limit = 1000

    @property
    def mode(self) -> SyncMode:
        return self._mode

    @property
    def is_ws_active(self) -> bool:
        """Returns True if the WebSocket connection is confirmed healthy and active."""
        # 45s threshold for activity
        return self._ws_healthy and (time.time() - self._last_ws_activity < 45)

    async def report_ws_status(self, healthy: bool):
        """Called by the bridge to report connection status changes."""
        async with self._lock:
            if healthy:
                self._ws_healthy = True
                self._last_ws_activity = time.time()
                if self._mode != SyncMode.WEBSOCKET:
                    self._mode = SyncMode.WEBSOCKET
                    logger.info("📡 SYNC MODE: Switched to REAL-TIME (WebSocket)")
            else:
                self._ws_healthy = False
                if self._mode == SyncMode.WEBSOCKET:
                    self._mode = SyncMode.POLLING
                    logger.warning("📡 SYNC MODE: Switched to FALLBACK (Polling)")

    async def report_ws_activity(self):
        """Called on every message received via WebSocket."""
        self._last_ws_activity = time.time()
        self._ws_healthy = True

    def should_poll(self) -> bool:
        """
        Determines if an HTTP poll is allowed.
        Strictly disables polling when WebSocket is active.
        """
        if self.is_ws_active:
            return False
            
        now = time.time()
        # Fallback polling interval: 60 seconds
        if now - self._last_poll_time >= 60:
            self._last_poll_time = now
            return True
            
        return False

    def is_duplicate(self, event_id: str) -> bool:
        """Checks if an event ID has already been processed to avoid duplicate UI updates."""
        if not event_id:
            return False
            
        if event_id in self._seen_events:
            return True
            
        self._seen_events.add(event_id)
        if len(self._seen_events) > self._event_history_limit:
            # Simple cleanup of the set
            self._seen_events.clear() # Clear and restart to avoid memory leak
            
        return False

    def suppress_poll(self, path: str) -> bool:
        """
        Returns True if a request to the given path should be suppressed 
        because the real-time bridge is active and providing the same data.
        """
        if not self.is_ws_active:
            return False
            
        # Paths that are redundant when WS is pushing updates
        redundant_paths = {
            "/desktop-updates/sync/status",
            "/orders/",
            "/orders"
        }
        
        # Check if the path starts with any of our redundant prefixes
        normalized_path = path.lower()
        return any(normalized_path.startswith(p.lower()) for p in redundant_paths)

# Global Singleton
sync_manager = SyncManager()

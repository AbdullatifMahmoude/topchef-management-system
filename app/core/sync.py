import asyncio
import time
from enum import Enum
from typing import Set

from app.core.logging import logger


class SyncMode(Enum):
    WEBSOCKET = "websocket"
    POLLING = "polling"
    OFFLINE = "offline"


class WebSocketConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"


class SyncManager:
    """
    Synchronization manager for real-time and fallback sync modes.

    WebSocket health is based on explicit transport state. An idle connection is
    healthy; lack of application messages must not trigger fallback polling.
    """

    def __init__(self):
        self._mode = SyncMode.POLLING
        self._last_ws_message_at = 0.0
        self._last_ws_state_change_at = 0.0
        self._last_poll_time = 0.0
        self._ws_state = WebSocketConnectionState.DISCONNECTED
        self._lock = asyncio.Lock()

        # Event Deduplication (Last 1000 event IDs)
        self._seen_events: Set[str] = set()
        self._event_history_limit = 1000

    @property
    def mode(self) -> SyncMode:
        return self._mode

    @property
    def ws_state(self) -> WebSocketConnectionState:
        return self._ws_state

    @property
    def is_ws_active(self) -> bool:
        """Return True while the WebSocket transport is connected."""
        return self._ws_state == WebSocketConnectionState.CONNECTED

    async def report_ws_status(self, healthy: bool):
        """Backward-compatible bridge status hook."""
        await self.report_ws_state(
            WebSocketConnectionState.CONNECTED if healthy else WebSocketConnectionState.DISCONNECTED
        )

    async def report_ws_state(self, state: WebSocketConnectionState, reason: str | None = None):
        """Called by the bridge to report explicit connection state changes."""
        async with self._lock:
            previous = self._ws_state
            self._ws_state = state
            self._last_ws_state_change_at = time.time()

            if state == WebSocketConnectionState.CONNECTED:
                if self._mode != SyncMode.WEBSOCKET:
                    self._mode = SyncMode.WEBSOCKET
                    logger.info("SYNC MODE: switched to REAL-TIME (WebSocket)")
            elif state in {WebSocketConnectionState.DISCONNECTED, WebSocketConnectionState.RECONNECTING}:
                if self._mode == SyncMode.WEBSOCKET:
                    self._mode = SyncMode.POLLING
                    logger.warning("SYNC MODE: switched to FALLBACK (Polling)")

            if previous != state:
                detail = f" reason={reason}" if reason else ""
                logger.info("WebSocket state transition: %s -> %s%s", previous.value, state.value, detail)

    async def report_ws_activity(self):
        """Record application-message activity for logs/diagnostics only."""
        self._last_ws_message_at = time.time()

    def should_poll(self) -> bool:
        """
        Determines if an HTTP poll is allowed.
        Strictly disables polling when WebSocket is connected.
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
            # Simple cleanup of the set.
            self._seen_events.clear()

        return False

    def suppress_poll(self, path: str) -> bool:
        """
        Returns True if a request to the given path should be suppressed
        because the real-time bridge is connected and providing the same data.
        """
        if not self.is_ws_active:
            return False

        redundant_paths = {
            "/orders/",
            "/orders",
        }

        normalized_path = path.lower()
        return any(normalized_path.startswith(p.lower()) for p in redundant_paths)


sync_manager = SyncManager()

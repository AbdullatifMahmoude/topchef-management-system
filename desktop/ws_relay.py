"""
WebSocket Relay — Real-Time Bridge
────────────────────────────────────
Connects to the cloud WebSocket at /orders/ws and relays all events
to locally connected frontend clients. This replaces polling with
true real-time push notifications, identical to the web service.

Architecture:
  Cloud WS ──► ws_relay (upstream client) ──► Local WS ──► Frontend
"""

import asyncio
import json
import threading
from typing import Any, Callable, Dict, List, Optional

from desktop.config import config
from desktop.logger import desktop_logger as log


class LocalConnectionManager:
    """Manages local WebSocket connections from the desktop frontend."""

    def __init__(self):
        self.active_connections: list = []
        self._lock = threading.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.append(websocket)
        log.info("✓ Local WS client connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket):
        with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        log.info("✗ Local WS client disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message dict to all connected local frontend clients."""
        dead = []
        payload = json.dumps(message, ensure_ascii=False)

        with self._lock:
            connections = list(self.active_connections)

        for conn in connections:
            try:
                await conn.send_text(payload)
            except Exception as exc:
                log.warning("Local WS send failed: %s", exc)
                dead.append(conn)

        if dead:
            with self._lock:
                for d in dead:
                    if d in self.active_connections:
                        self.active_connections.remove(d)

    @property
    def client_count(self) -> int:
        return len(self.active_connections)


# Global instance for the local desktop WebSocket hub
local_ws_manager = LocalConnectionManager()


class CloudWebSocketRelay:
    """
    Persistent WebSocket client that connects to the cloud server's
    /orders/ws endpoint and relays every incoming event to the local
    frontend via local_ws_manager.broadcast().

    Features:
    - Auto-reconnect with exponential backoff
    - Thread-safe start/stop
    - Callback hook for sync engine integration
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_event_callbacks: List[Callable] = []
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        """Register a callback that fires on every cloud WS event."""
        self._on_event_callbacks.append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ws-relay",
            daemon=True,
        )
        self._thread.start()
        log.info("Cloud WebSocket relay started.")

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Cloud WebSocket relay stopped.")

    def _run_loop(self):
        """Dedicated thread event loop for the upstream WS client."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_forever())
        except Exception as exc:
            log.error("WS relay loop exited: %s", exc)
        finally:
            self._loop.close()

    async def _connect_forever(self):
        """Reconnection loop: connect → listen → on close → backoff → retry."""
        import websockets

        # Build WS URL from config
        base = config.server_url.rstrip("/")
        ws_url = base.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/orders/ws"

        while self._running:
            try:
                log.info("Connecting to cloud WebSocket: %s", ws_url)

                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    additional_headers={"User-Agent": "TopChefDesktopPOS/2.0"},
                ) as ws:
                    log.info("✓ Cloud WebSocket connected.")
                    self._connected = True
                    self._reconnect_delay = 1.0  # Reset backoff on success

                    try:
                        async for raw_message in ws:
                            if not self._running:
                                break
                            await self._handle_cloud_message(raw_message)
                    except websockets.ConnectionClosed as exc:
                        log.warning("Cloud WS connection closed: code=%s reason=%s",
                                    exc.code, exc.reason)

            except Exception as exc:
                log.warning("Cloud WS connection failed: %s", exc)
            finally:
                self._connected = False

            if not self._running:
                break

            # Exponential backoff
            delay = min(self._reconnect_delay, self._max_reconnect_delay)
            log.info("Reconnecting to cloud WS in %.1fs...", delay)
            await asyncio.sleep(delay)
            self._reconnect_delay = min(self._reconnect_delay * 1.5, self._max_reconnect_delay)

    async def _handle_cloud_message(self, raw_message: str):
        """Parse and relay a message from the cloud to local clients + callbacks."""
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from cloud WS: %s", raw_message[:200])
            return

        event_type = data.get("event", "unknown")
        log.info("☁ Cloud WS event received: %s", event_type)

        # 1. Relay to all local frontend WebSocket clients
        await local_ws_manager.broadcast(data)

        # 2. Fire registered callbacks (e.g., sync engine to update local DB)
        for cb in self._on_event_callbacks:
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.error("WS event callback error: %s", exc)


# Global singleton
cloud_ws_relay = CloudWebSocketRelay()

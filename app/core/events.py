import asyncio
import contextlib
import json
from enum import Enum
from typing import Any, Callable

from fastapi import WebSocket

from app.core.config import settings
from app.core.logging import logger
from app.core.redis import redis_client


class Event:
    def __init__(self, name: str, data: Any = None):
        self.name = name
        self.data = data


class OrderEvents(str, Enum):
    CREATED = "order.created"
    UPDATED = "order.updated"
    STATUS_CHANGED = "order.status_changed"


class AuthEvents(str, Enum):
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    async def emit(self, event_name: str, data: Any = None):
        if event_name not in self._subscribers:
            return
        callbacks = self._subscribers[event_name]
        if not callbacks:
            return
        tasks = [callback(data) for callback in callbacks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for index, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Error in subscriber %s for %s: %s",
                    getattr(callbacks[index], "__name__", "anonymous"),
                    event_name,
                    result,
                )


event_bus = EventBus()
outbox_sync_trigger = asyncio.Event()


class OrderEventsManager:
    CHANNEL_PREFIX = "topchef:orders:events"

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._listener_task: asyncio.Task | None = None
        self._remote_bridge_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if settings.RUNTIME_MODE == "desktop":
            if not self._remote_bridge_task:
                self._remote_bridge_task = asyncio.create_task(
                    self._desktop_remote_listener_loop(),
                    name="desktop-order-events-bridge",
                )
                logger.info("Order events manager started with desktop remote bridge")
            return

        if redis_client.backend_name == "redis" and not self._listener_task:
            self._listener_task = asyncio.create_task(self._redis_listener(), name="order-events-listener")
            logger.info("Order events manager started with Redis pub/sub backend")

    async def stop(self) -> None:
        if not self._listener_task:
            pass
        else:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        if self._remote_bridge_task:
            self._remote_bridge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._remote_bridge_task
            self._remote_bridge_task = None
        logger.info("Order events manager stopped")

    async def connect(self, websocket: WebSocket, channel: str = "default"):
        await websocket.accept()
        async with self._lock:
            if channel not in self.active_connections:
                self.active_connections[channel] = []
            self.active_connections[channel].append(websocket)
            connection_count = sum(len(conns) for conns in self.active_connections.values())
        logger.info("New WebSocket connection in channel '%s'. Total: %s", channel, connection_count)

    async def disconnect(self, websocket: WebSocket, channel: str = "default"):
        async with self._lock:
            if channel in self.active_connections and websocket in self.active_connections[channel]:
                self.active_connections[channel].remove(websocket)
            connection_count = sum(len(conns) for conns in self.active_connections.values())
        logger.info("WebSocket disconnected from channel '%s'. Total: %s", channel, connection_count)

    async def broadcast(self, message: dict[str, Any], channel: str = "default"):
        async with self._lock:
            connections = list(self.active_connections.get(channel, []))
        if not connections:
            return

        payload = json.dumps(message)

        async def _safe_send(connection: WebSocket):
            try:
                await connection.send_text(payload)
                return None
            except Exception as exc:
                logger.error("WebSocket send failed in channel '%s': %s", channel, exc)
                return connection

        dead_connections = [conn for conn in await asyncio.gather(*[_safe_send(conn) for conn in connections]) if conn]
        for dead in dead_connections:
            await self.disconnect(dead, channel)

    def emit(self, message: dict[str, Any], channel: str = "default"):
        asyncio.create_task(self._emit(message, channel))

    async def _emit(self, message: dict[str, Any], channel: str = "default") -> None:
        redis_channel = f"{self.CHANNEL_PREFIX}:{channel}"
        if redis_client.backend_name == "redis" and redis_client.redis is not None:
            try:
                await redis_client.redis.publish(redis_channel, json.dumps(message))
                return
            except Exception as exc:
                logger.warning("Redis publish failed for channel '%s', falling back to local broadcast: %s", channel, exc)
        await self.broadcast(message, channel)

    async def _redis_listener(self) -> None:
        if redis_client.redis is None:
            return
        pubsub = redis_client.redis.pubsub()
        # Subscribe to all channels under prefix
        await pubsub.psubscribe(f"{self.CHANNEL_PREFIX}:*")
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message:
                    await asyncio.sleep(0.05)
                    continue
                
                raw_channel = message.get("channel")
                if isinstance(raw_channel, bytes):
                    raw_channel = raw_channel.decode("utf-8")
                
                # Extract local channel name
                channel = raw_channel.replace(f"{self.CHANNEL_PREFIX}:", "")
                
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    payload = json.loads(data)
                except Exception as exc:
                    logger.warning("Failed to decode pub/sub event: %s", exc)
                    continue
                await self.broadcast(payload, channel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Order events Redis listener failed: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.punsubscribe(f"{self.CHANNEL_PREFIX}:*")
            with contextlib.suppress(Exception):
                await pubsub.close()

    async def _desktop_remote_listener_loop(self) -> None:
        import websockets
        import json
        from app.core.sync import sync_manager

        base_url = settings.REMOTE_API.rstrip("/")
        ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/orders/ws"
        reconnect_delay = 1.0

        while True:
            try:
                connection_start_time = time.time()
                logger.info("Connecting desktop real-time bridge to %s", ws_url)
                async with websockets.connect(
                    ws_url,
                    ping_interval=30,  # Send ping every 30s
                    ping_timeout=20,   # Timeout after 20s if no pong
                    close_timeout=10,
                    additional_headers={"User-Agent": "TopChefDesktopBridge/1.0"},
                ) as ws:
                    reconnect_delay = 1.0
                    await sync_manager.report_ws_status(True)
                    logger.info("🟢 Desktop real-time bridge connected to cloud.")

                    async def send_heartbeat():
                        while True:
                            try:
                                await asyncio.sleep(45)
                                await ws.send(json.dumps({"type": "heartbeat"}))
                            except: break
                    
                    hb_task = asyncio.create_task(send_heartbeat())
                    try:
                        async for raw_message in ws:
                            # Only reset backoff if connection was stable for 30s
                            if time.time() - connection_start_time > 30:
                                reconnect_delay = 1.0
                            await sync_manager.report_ws_activity()
                            try:
                                payload = json.loads(raw_message)
                            except Exception as exc:
                                logger.warning("Desktop bridge received invalid JSON: %s", exc)
                                continue

                            event_id = payload.get("id") or payload.get("order_id")
                            if sync_manager.is_duplicate(str(event_id)):
                                continue

                            if payload.get("event") not in {
                                OrderEvents.CREATED.value,
                                OrderEvents.UPDATED.value,
                                OrderEvents.STATUS_CHANGED.value,
                            }:
                                continue

                            # Broadcast to all local channels
                            for channel in list(self.active_connections.keys()):
                                await self.broadcast(payload, channel)
                    finally:
                        hb_task.cancel()

            except asyncio.CancelledError:
                await sync_manager.report_ws_status(False)
                logger.info("Gracefully closing desktop bridge connection...")
                raise
            except Exception as exc:
                await sync_manager.report_ws_status(False)
                logger.warning("🔴 Bridge disconnected: %s. Reconnecting in %.1fs...", exc, reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff: 1.5x + 1s, max 60s
                reconnect_delay = min(reconnect_delay * 1.5 + 1.0, 60.0)


order_events_manager = OrderEventsManager()

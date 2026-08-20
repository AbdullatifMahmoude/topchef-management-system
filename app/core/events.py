import asyncio
import contextlib
import json
from enum import Enum
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

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
        self._subscribers.setdefault(event_name, []).append(callback)

    async def emit(self, event_name: str, data: Any = None):
        callbacks = self._subscribers.get(event_name, [])
        results = await asyncio.gather(
            *(callback(data) for callback in callbacks), return_exceptions=True
        )
        for callback, result in zip(callbacks, results):
            if isinstance(result, Exception):
                logger.error(
                    "Error in subscriber %s for %s: %s",
                    getattr(callback, "__name__", "anonymous"), event_name, result,
                )


event_bus = EventBus()


class OrderEventsManager:
    CHANNEL_PREFIX = "topchef:orders:events"
    CLIENT_HEARTBEAT_INTERVAL_SECONDS = 25.0

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._connection_channels: dict[WebSocket, str] = {}
        self._heartbeat_tasks: dict[WebSocket, asyncio.Task] = {}
        self._listener_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if redis_client.backend_name == "redis" and not self._listener_task:
            self._listener_task = asyncio.create_task(
                self._redis_listener(), name="order-events-listener"
            )
            logger.info("Order events manager started with Redis pub/sub backend")

    async def stop(self) -> None:
        async with self._lock:
            connections = list(self._connection_channels)
        for websocket in connections:
            await self.disconnect(websocket)
        if self._listener_task:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        logger.info("Order events manager stopped")

    async def connect(self, websocket: WebSocket, channel: str = "default"):
        await websocket.accept()
        async with self._lock:
            self.active_connections.setdefault(channel, []).append(websocket)
            self._connection_channels[websocket] = channel
            self._heartbeat_tasks[websocket] = asyncio.create_task(
                self._send_heartbeat(websocket), name=f"orders-ws-heartbeat-{channel}"
            )

    async def disconnect(self, websocket: WebSocket, channel: str = "default"):
        async with self._lock:
            channel = self._connection_channels.pop(websocket, channel)
            heartbeat_task = self._heartbeat_tasks.pop(websocket, None)
            connections = self.active_connections.get(channel, [])
            if websocket in connections:
                connections.remove(websocket)
            if not connections:
                self.active_connections.pop(channel, None)
        if heartbeat_task:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _send_heartbeat(self, websocket: WebSocket) -> None:
        while True:
            try:
                await asyncio.sleep(self.CLIENT_HEARTBEAT_INTERVAL_SECONDS)
                await websocket.send_json({"type": "HEARTBEAT"})
            except asyncio.CancelledError:
                raise
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.debug("Client heartbeat stopped: %s", exc)
                break

    async def broadcast(self, message: dict[str, Any], channel: str = "default"):
        async with self._lock:
            connections = list(self.active_connections.get(channel, []))
        payload = json.dumps(message)

        async def send(connection: WebSocket):
            try:
                await connection.send_text(payload)
            except Exception:
                return connection
            return None

        results = await asyncio.gather(*(send(item) for item in connections))
        for dead in (item for item in results if item):
            await self.disconnect(dead, channel)

    async def broadcast_all(self, message: dict[str, Any]):
        async with self._lock:
            channels = list(self.active_connections)
        for channel in channels:
            await self.broadcast(message, channel)

    async def emit(self, message: dict[str, Any], channel: str = "default"):
        if channel == "default":
            await self.broadcast_all(message)
        else:
            await self.broadcast(message, channel)
        if redis_client.backend_name == "redis" and redis_client.redis is not None:
            try:
                await redis_client.redis.publish(
                    f"{self.CHANNEL_PREFIX}:{channel}", json.dumps(message)
                )
            except Exception as exc:
                logger.warning("Redis publish failed for channel '%s': %s", channel, exc)

    async def _redis_listener(self) -> None:
        if redis_client.redis is None:
            return
        while True:
            pubsub = redis_client.redis.pubsub()
            try:
                await pubsub.psubscribe(f"{self.CHANNEL_PREFIX}:*")
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if not message:
                        await asyncio.sleep(0.05)
                        continue
                    raw_channel = message.get("channel")
                    if isinstance(raw_channel, bytes):
                        raw_channel = raw_channel.decode("utf-8")
                    channel = raw_channel.replace(f"{self.CHANNEL_PREFIX}:", "")
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    payload = json.loads(data)
                    if channel == "default":
                        await self.broadcast_all(payload)
                    else:
                        await self.broadcast(payload, channel)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Order events Redis listener failed: %s", exc)
                await asyncio.sleep(5)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.punsubscribe(f"{self.CHANNEL_PREFIX}:*")
                    await pubsub.close()


order_events_manager = OrderEventsManager()

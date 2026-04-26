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


class OrderEventsManager:
    CHANNEL_NAME = "topchef:orders:events"

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
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

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            connection_count = len(self.active_connections)
        logger.info("New WebSocket connection. Total: %s", connection_count)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            connection_count = len(self.active_connections)
        logger.info("WebSocket disconnected. Total: %s", connection_count)

    async def broadcast(self, message: dict[str, Any]):
        async with self._lock:
            connections = list(self.active_connections)
        if not connections:
            return

        payload = json.dumps(message)

        async def _safe_send(connection: WebSocket):
            try:
                await connection.send_text(payload)
                return None
            except Exception as exc:
                logger.error("WebSocket send failed: %s", exc)
                return connection

        dead_connections = [conn for conn in await asyncio.gather(*[_safe_send(conn) for conn in connections]) if conn]
        for dead in dead_connections:
            await self.disconnect(dead)

    def emit(self, message: dict[str, Any]):
        asyncio.create_task(self._emit(message))

    async def _emit(self, message: dict[str, Any]) -> None:
        if redis_client.backend_name == "redis" and redis_client.redis is not None:
            try:
                await redis_client.redis.publish(self.CHANNEL_NAME, json.dumps(message))
                return
            except Exception as exc:
                logger.warning("Redis publish failed, falling back to local broadcast: %s", exc)
        await self.broadcast(message)

    async def _redis_listener(self) -> None:
        if redis_client.redis is None:
            return
        pubsub = redis_client.redis.pubsub()
        await pubsub.subscribe(self.CHANNEL_NAME)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message:
                    await asyncio.sleep(0.05)
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    payload = json.loads(data)
                except Exception as exc:
                    logger.warning("Failed to decode pub/sub event: %s", exc)
                    continue
                await self.broadcast(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Order events Redis listener failed: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self.CHANNEL_NAME)
            with contextlib.suppress(Exception):
                await pubsub.close()

    async def _desktop_remote_listener_loop(self) -> None:
        import websockets

        base_url = settings.REMOTE_API.rstrip("/")
        ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/orders/ws"
        reconnect_delay = 1.0

        while True:
            try:
                logger.info("Connecting desktop real-time bridge to %s", ws_url)
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    additional_headers={"User-Agent": "TopChefDesktopBridge/1.0"},
                ) as ws:
                    reconnect_delay = 1.0
                    logger.info("Desktop real-time bridge connected to cloud orders WebSocket")
                    async for raw_message in ws:
                        try:
                            payload = json.loads(raw_message)
                        except Exception as exc:
                            logger.warning("Desktop bridge received invalid JSON: %s", exc)
                            continue
                        if payload.get("event") not in {
                            OrderEvents.CREATED.value,
                            OrderEvents.UPDATED.value,
                            OrderEvents.STATUS_CHANGED.value,
                        }:
                            continue
                        await self.broadcast(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Desktop real-time bridge disconnected: %s", exc)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, 30.0)


order_events_manager = OrderEventsManager()

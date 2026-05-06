import asyncio
import contextlib
import inspect
import json
import random
import time
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
    DESKTOP_HEARTBEAT_INTERVAL_SECONDS = 25.0
    DESKTOP_STABLE_AFTER_SECONDS = 30.0

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._listener_task: asyncio.Task | None = None
        self._remote_bridge_task: asyncio.Task | None = None
        self._remote_bridge_ws: Any | None = None
        self._remote_bridge_connect_lock = asyncio.Lock()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if settings.RUNTIME_MODE == "desktop":
            if not self._remote_bridge_task or self._remote_bridge_task.done():
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
        if self._listener_task:
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

    async def broadcast_all(self, message: dict[str, Any]):
        async with self._lock:
            channels = list(self.active_connections.keys())
        for channel in channels:
            await self.broadcast(message, channel)

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
        if channel == "default":
            await self.broadcast_all(message)
            return
        await self.broadcast(message, channel)

    async def _redis_listener(self) -> None:
        if redis_client.redis is None:
            return
        pubsub = redis_client.redis.pubsub()
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

                channel = raw_channel.replace(f"{self.CHANNEL_PREFIX}:", "")

                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    payload = json.loads(data)
                except Exception as exc:
                    logger.warning("Failed to decode pub/sub event: %s", exc)
                    continue
                if channel == "default":
                    await self.broadcast_all(payload)
                else:
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
        from app.core.sync import WebSocketConnectionState, sync_manager

        base_url = settings.REMOTE_API.rstrip("/")
        ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/orders/ws"
        backoff_seconds = 1.0
        attempt = 0

        connect_params: dict[str, Any] = {
            "ping_interval": 30,
            "ping_timeout": 20,
            "close_timeout": 10,
            "max_queue": 64,
        }
        header_param = "additional_headers"
        with contextlib.suppress(Exception):
            signature = inspect.signature(websockets.connect)
            if "extra_headers" in signature.parameters:
                header_param = "extra_headers"
        connect_params[header_param] = {"User-Agent": "TopChefDesktopBridge/1.0"}

        while True:
            ws = None
            retry_after = 0.0
            cleanup_state = True
            try:
                state = (
                    WebSocketConnectionState.CONNECTING
                    if attempt == 0
                    else WebSocketConnectionState.RECONNECTING
                )
                await sync_manager.report_ws_state(state, reason=f"attempt={attempt + 1}")

                async with self._remote_bridge_connect_lock:
                    if self._remote_bridge_ws is not None:
                        logger.warning("Skipping bridge connect because a WebSocket is already active")
                        cleanup_state = False
                        await asyncio.sleep(backoff_seconds)
                        continue

                    logger.info("Desktop bridge connecting to %s attempt=%s", ws_url, attempt + 1)
                    ws = await self._desktop_connect(ws_url, connect_params)
                    self._remote_bridge_ws = ws

                await sync_manager.report_ws_state(WebSocketConnectionState.CONNECTED)
                logger.info(
                    "Desktop bridge connected to cloud ping_interval=%ss ping_timeout=%ss",
                    connect_params["ping_interval"],
                    connect_params["ping_timeout"],
                )
                connection_started_at = time.monotonic()

                await self._desktop_run_connection(ws, connection_started_at)
                if time.monotonic() - connection_started_at >= self.DESKTOP_STABLE_AFTER_SECONDS:
                    backoff_seconds = 1.0
                    attempt = 0

                raise ConnectionError("remote WebSocket closed without error")

            except asyncio.CancelledError:
                await sync_manager.report_ws_state(WebSocketConnectionState.STOPPING, reason="manager_stop")
                raise
            except Exception as exc:
                alive_for = 0.0
                if ws is not None:
                    alive_for = max(0.0, time.monotonic() - connection_started_at)
                await sync_manager.report_ws_state(
                    WebSocketConnectionState.RECONNECTING,
                    reason=f"{type(exc).__name__}: {exc}",
                )
                jitter = random.uniform(0, min(backoff_seconds * 0.25, 5.0))
                sleep_for = backoff_seconds + jitter
                reason_text = self._desktop_disconnect_reason(exc)
                logger.warning(
                    "🔴 Disconnected (reason=%s) exception=%s: %s; reconnecting in %.1fs",
                    reason_text,
                    type(exc).__name__,
                    exc,
                    sleep_for,
                )
                if alive_for:
                    logger.info("🟢 Connection alive for %.0fs", alive_for)
                retry_after = sleep_for
                attempt += 1
                backoff_seconds = min(backoff_seconds * 1.5 + 1.0, 60.0)
            finally:
                if ws is not None:
                    with contextlib.suppress(Exception):
                        await ws.close(code=1000, reason="desktop bridge cleanup")
                if self._remote_bridge_ws is ws:
                    self._remote_bridge_ws = None
                if cleanup_state and sync_manager.ws_state != WebSocketConnectionState.STOPPING:
                    next_state = (
                        WebSocketConnectionState.RECONNECTING
                        if retry_after
                        else WebSocketConnectionState.DISCONNECTED
                    )
                    await sync_manager.report_ws_state(next_state, reason="cleanup_complete")

            if retry_after:
                await asyncio.sleep(retry_after)

    async def _desktop_connect(self, ws_url: str, connect_params: dict[str, Any]):
        import websockets

        return await websockets.connect(ws_url, **connect_params)

    async def _desktop_run_connection(self, ws: Any, connection_started_at: float) -> None:
        heartbeat_task = asyncio.create_task(
            self._desktop_send_heartbeat(ws, connection_started_at),
            name="desktop-order-events-heartbeat",
        )
        listen_task = asyncio.create_task(
            self._desktop_listen(ws, connection_started_at),
            name="desktop-order-events-listen",
        )

        done, pending = await asyncio.wait(
            {heartbeat_task, listen_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )

        first_exception: Exception | None = None
        for task in done:
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                first_exception = exc

        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if first_exception is not None:
            raise first_exception

    async def _desktop_listen(self, ws: Any, connection_started_at: float) -> None:
        from app.core.sync import sync_manager

        async for raw_message in ws:
            alive_for = time.monotonic() - connection_started_at
            if alive_for >= self.DESKTOP_STABLE_AFTER_SECONDS:
                logger.debug("🟢 Connection alive for %.0fs", alive_for)

            await sync_manager.report_ws_activity()
            try:
                payload = json.loads(raw_message)
            except Exception as exc:
                logger.warning("Desktop bridge received invalid JSON: %s", exc)
                continue

            if payload.get("type") == "heartbeat_ack":
                logger.debug("Desktop bridge received heartbeat ack")
                continue

            event_name = payload.get("event")
            if event_name not in {
                OrderEvents.CREATED.value,
                OrderEvents.UPDATED.value,
                OrderEvents.STATUS_CHANGED.value,
            }:
                continue

            event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            event_id = (
                payload.get("id")
                or payload.get("order_id")
                or event_data.get("id")
                or event_data.get("order_number")
            )
            if event_id and sync_manager.is_duplicate(str(event_id)):
                logger.debug("Desktop bridge ignored duplicate event id=%s", event_id)
                continue

            await self.broadcast_all(payload)

    async def _desktop_send_heartbeat(self, ws: Any, connection_started_at: float) -> None:
        heartbeat_payload = json.dumps({"type": "heartbeat"})
        while True:
            await asyncio.sleep(self.DESKTOP_HEARTBEAT_INTERVAL_SECONDS)
            await ws.send(heartbeat_payload)
            alive_for = time.monotonic() - connection_started_at
            logger.info("💓 WebSocket heartbeat sent")
            logger.info("🟢 Connection alive for %.0fs", alive_for)

    def _desktop_disconnect_reason(self, exc: Exception) -> str:
        message = str(exc).lower()
        if "keepalive ping timeout" in message or "timed out waiting for keepalive pong" in message:
            return "ping timeout"
        if "no close frame" in message:
            return "abrupt close"
        if "closed without error" in message:
            return "idle timeout suspected"
        if "1000" in message:
            return "normal close"
        return "connection closed"


order_events_manager = OrderEventsManager()

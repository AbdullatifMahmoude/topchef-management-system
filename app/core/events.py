import asyncio
import contextlib
import inspect
import json
import random
import time
from enum import Enum
from typing import Any, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

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
_outbox_sync_event: Optional[asyncio.Event] = None


def get_outbox_sync_trigger() -> asyncio.Event:
    """Returns a shared asyncio.Event used to wake the desktop sync loop instantly.

    The event is lazily created on first access so that it is always bound to
    the running event-loop.  Callers use ``.set()`` to wake the sync worker
    and the worker calls ``.wait()`` / ``.clear()`` as usual.
    """
    global _outbox_sync_event
    if _outbox_sync_event is None:
        _outbox_sync_event = asyncio.Event()
    return _outbox_sync_event


class OrderEventsManager:
    CHANNEL_PREFIX = "topchef:orders:events"
    CLIENT_HEARTBEAT_INTERVAL_SECONDS = 25.0
    DESKTOP_HEARTBEAT_INTERVAL_SECONDS = 25.0
    DESKTOP_STABLE_AFTER_SECONDS = 30.0

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._connection_channels: dict[WebSocket, str] = {}
        self._heartbeat_tasks: dict[WebSocket, asyncio.Task] = {}
        self._listener_task: asyncio.Task | None = None
        self._remote_bridge_task: asyncio.Task | None = None
        self._remote_bridge_ws: Any | None = None
        self._remote_bridge_connect_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

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
        async with self._lock:
            connections = list(self._connection_channels.keys())

        for websocket in connections:
            await self.disconnect(websocket)

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
            self._connection_channels[websocket] = channel
            self._heartbeat_tasks[websocket] = asyncio.create_task(
                self._send_client_heartbeat(websocket),
                name=f"orders-ws-heartbeat-{channel}",
            )
            connection_count = sum(len(conns) for conns in self.active_connections.values())
        logger.info("New WebSocket connection in channel '%s'. Total: %s", channel, connection_count)

    async def disconnect(self, websocket: WebSocket, channel: str = "default"):
        heartbeat_task: asyncio.Task | None = None
        async with self._lock:
            channel = self._connection_channels.pop(websocket, channel)
            heartbeat_task = self._heartbeat_tasks.pop(websocket, None)
            connections = self.active_connections.get(channel)
            if connections and websocket in connections:
                connections.remove(websocket)
                if not connections:
                    self.active_connections.pop(channel, None)
            connection_count = sum(len(conns) for conns in self.active_connections.values())

        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        logger.info("WebSocket disconnected from channel '%s'. Total: %s", channel, connection_count)

    async def _send_client_heartbeat(self, websocket: WebSocket) -> None:
        while True:
            try:
                await asyncio.sleep(self.CLIENT_HEARTBEAT_INTERVAL_SECONDS)
                await websocket.send_json({"type": "HEARTBEAT"})
            except asyncio.CancelledError:
                raise
            except (WebSocketDisconnect, RuntimeError) as exc:
                logger.debug("Client heartbeat stopped because WebSocket closed: %s", exc)
                break
            except Exception as exc:
                try:
                    import websockets

                    if isinstance(exc, websockets.exceptions.ConnectionClosed):
                        break
                except Exception:
                    pass
                logger.debug("Client heartbeat stopped after send failure: %s", exc)
                break

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

    async def emit(self, message: dict[str, Any], channel: str = "default"):
        await self._emit(message, channel)

    async def _emit(self, message: dict[str, Any], channel: str = "default") -> None:
        # 1. Immediate local broadcast (fastest, hits local clients)
        if channel == "default":
            await self.broadcast_all(message)
        else:
            await self.broadcast(message, channel)
            
        # 2. Publish to Redis for other workers (echo will be deduplicated by clients)
        redis_channel = f"{self.CHANNEL_PREFIX}:{channel}"
        if redis_client.backend_name == "redis" and redis_client.redis is not None:
            try:
                await redis_client.redis.publish(redis_channel, json.dumps(message))
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
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    except TimeoutError:
                        continue
                        
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
                logger.error("Order events Redis listener failed: %s. Reconnecting in 5s...", exc)
                await asyncio.sleep(5)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.punsubscribe(f"{self.CHANNEL_PREFIX}:*")
                try:
                    await pubsub.close()
                except Exception as close_exc:
                    logger.debug("pubsub.close() failed: %s", close_exc)

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
            connection_started_at = 0.0
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
                # Reconnect: drain outbox and request incremental catch-up (not full pull).
                from app.core.sync_triggers import request_incremental_pull
                request_incremental_pull()
                get_outbox_sync_trigger().set()
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
                if ws is not None and connection_started_at > 0:
                    alive_for = max(0.0, time.monotonic() - connection_started_at)
                    if alive_for >= self.DESKTOP_STABLE_AFTER_SECONDS:
                        backoff_seconds = 1.0
                        attempt = 0
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
            return_when=asyncio.FIRST_COMPLETED,
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

            if str(payload.get("type") or "").lower() in {"heartbeat_ack"}:
                logger.debug("Desktop bridge received heartbeat ack")
                continue

            event_name = payload.get("event") or payload.get("type")
            if event_name not in {
                OrderEvents.CREATED.value,
                OrderEvents.UPDATED.value,
                OrderEvents.STATUS_CHANGED.value,
                "SETTING_UPDATED",
                "NEW_ORDER",
                "ORDER_UPDATED",
                "CUSTOMER_CREATED",
                "ADDRESS_CREATED",
                "PRODUCT_UPDATED",
                "CATEGORY_UPDATED",
                "VARIANT_UPDATED",
                "OFFER_UPDATED",
                "SHIFT_CREATED",
                "SHIFT_UPDATED",
            }:
                # Also check top-level type
                if payload.get("type") not in {
                    "SETTING_UPDATED", "NEW_ORDER", "ORDER_UPDATED", "ORDER_SNAPSHOT",
                    "CUSTOMER_CREATED", "ADDRESS_CREATED", "PRODUCT_UPDATED",
                    "CATEGORY_UPDATED", "VARIANT_UPDATED", "OFFER_UPDATED",
                    "SHIFT_CREATED", "SHIFT_UPDATED",
                }:
                    continue

            event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            event_id = (
                payload.get("id")  # Unique Event ID (UUID)
                or f"{event_name}_{event_data.get('id') or event_data.get('order_number')}" # Composite key
            )
            if event_id and sync_manager.is_duplicate(str(event_id)):
                logger.debug("Desktop bridge ignored duplicate event id=%s", event_id)
                continue

            # 3. ID Remapping for Desktop consistency
            # If we receive an order event from the cloud, try to find if we have it locally
            # by order_number + date. if so, remap the ID to the local one so the frontend
            # doesn't send cloud IDs to the local API (which causes 404).
            if event_name in {OrderEvents.CREATED.value, OrderEvents.UPDATED.value, OrderEvents.STATUS_CHANGED.value, "NEW_ORDER", "ORDER_UPDATED"}:
                order_num = event_data.get("order_number")
                order_date = event_data.get("order_date")
                if order_num and order_date:
                    from app.core.database import AsyncSessionLocal
                    from sqlalchemy import select
                    from app.modules.orders.models import Order
                    
                    try:
                        from datetime import date
                        parsed_date = order_date
                        if isinstance(order_date, str):
                            parsed_date = date.fromisoformat(order_date[:10])
                            
                        async with AsyncSessionLocal() as session:
                            stmt = select(Order.id).where(Order.order_number == order_num, Order.order_date == parsed_date)
                            local_id = await session.scalar(stmt)
                            if local_id:
                                payload["data"]["id"] = local_id
                                # Also update top-level ID if it exists
                                if "id" in payload:
                                    payload["id"] = local_id
                    except Exception as e:
                        logger.warning("Failed to remap cloud order ID for event: %s", e)

            # 4. Trigger Sync Pull for order/customer events to ensure local DB is up to date with cloud truth
            if event_name in {
                OrderEvents.CREATED.value, "NEW_ORDER", 
                OrderEvents.UPDATED.value, "ORDER_UPDATED",
                OrderEvents.STATUS_CHANGED.value,
                "CUSTOMER_CREATED", "ADDRESS_CREATED", "SETTING_UPDATED",
                "PRODUCT_UPDATED", "CATEGORY_UPDATED", "VARIANT_UPDATED", "OFFER_UPDATED",
            }:
                get_outbox_sync_trigger().set()

            await self.broadcast_all(payload)

    async def _desktop_send_heartbeat(self, ws: Any, connection_started_at: float) -> None:
        import websockets

        heartbeat_payload = json.dumps({"type": "heartbeat"})
        while True:
            try:
                await asyncio.sleep(self.DESKTOP_HEARTBEAT_INTERVAL_SECONDS)
                await ws.send(heartbeat_payload)
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed:
                break
            alive_for = time.monotonic() - connection_started_at
            logger.debug("💓 WebSocket heartbeat sent")
            logger.debug("🟢 Connection alive for %.0fs", alive_for)

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

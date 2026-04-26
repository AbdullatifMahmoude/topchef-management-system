import asyncio
import json
from enum import Enum
from typing import List, Dict, Any, Callable
from fastapi import WebSocket
from app.core.logging import logger

# Base Event class
class Event:
    def __init__(self, name: str, data: Any = None):
        self.name = name
        self.data = data

# Event enumerations for system-wide consistency
class OrderEvents(str, Enum):
    CREATED = "order.created"
    UPDATED = "order.updated"
    STATUS_CHANGED = "order.status_changed"

class AuthEvents(str, Enum):
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"

# Simple internal Event Bus for server-side event handling
class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    async def emit(self, event_name: str, data: Any = None):
        """Emit internal event and run all subscribers in parallel."""
        if event_name in self._subscribers:
            callbacks = self._subscribers[event_name]
            if not callbacks:
                return
            
            # Run all subscribers in parallel for maximum speed
            tasks = [callback(data) for callback in callbacks]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log any errors from subscribers
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error in subscriber {callbacks[i].__name__} for {event_name}: {result}")

# Global internal event bus instance
event_bus = EventBus()

# WebSocket Connection Manager for real-time frontend notifications
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✓ New WebSocket connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            try:
                self.active_connections.remove(websocket)
            except ValueError:
                pass
            logger.info(f"✗ WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients in parallel."""
        if not self.active_connections:
            return

        payload = json.dumps(message)
        
        # Create send tasks for all connections
        # We use a wrapper to handle exceptions per-connection
        async def _safe_send(connection: WebSocket):
            try:
                await connection.send_text(payload)
                return True
            except Exception as e:
                logger.error(f"WebSocket send failed: {e}")
                return connection

        # Run all sends in parallel
        tasks = [_safe_send(conn) for conn in self.active_connections]
        results = await asyncio.gather(*tasks)
        
        # Clean up dead connections (those that returned the connection object instead of True)
        dead_connections = [res for res in results if res is not True]
        for dead in dead_connections:
            self.disconnect(dead)

    def emit(self, message: Dict[str, Any]):
        """Schedule a broadcast in the background without blocking the current request."""
        asyncio.create_task(self.broadcast(message))

# Global manager instance for orders module
order_events_manager = ConnectionManager()

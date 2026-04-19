from enum import Enum
from typing import List, Dict, Any, Callable
import json
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
        if event_name in self._subscribers:
            for callback in self._subscribers[event_name]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Error in event subscriber for {event_name}: {e}")

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
        """Broadcast message to all connected clients."""
        dead_connections = []
        payload = json.dumps(message)
        
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                dead_connections.append(connection)
        
        # Cleanup broken connections
        for dead in dead_connections:
            self.disconnect(dead)

# Global manager instance for orders module
order_events_manager = ConnectionManager()

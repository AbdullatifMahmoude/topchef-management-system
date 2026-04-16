from fastapi import WebSocket
from typing import List, Dict, Any
import json
from app.core.logging import logger

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✓ New WebSocket connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
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

# Global manager instance
order_events_manager = ConnectionManager()

import asyncio
from typing import Callable, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Event:
    name: str
    payload: Dict[str, Any]
    timestamp: datetime = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


class EventBus:

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._middlewares: List[Callable] = []

    def subscribe(self, event_name: str, handler=Callable):
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler=Callable):
        self._handlers[event_name].remove(handler)

    def add_middleware(self, middleware: Callable):
        self._middlewares.append(middleware)

    async def publish(self, event: Event):

        for middleware in self._middlewares:
            await middleware(event)

        handlers = self._handlers.get(event.name, [])
        tasks = [
            self._run_handler(handler, event)
            for handler in handlers
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_handler(self, handler: Callable, event: Event):
        try:
            if asyncio.iscoroutine(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            print(f"event handler error: {e}")

    def get_handler(self, event_name: Event) -> List[Callable]:
        return self._handlers.get(event_name, [])


event_bus = EventBus()


class OrderEvents:
    CREATED = "order.created"
    CONFIRMED = "order.confirmed"
    COMPLETED = "order.completed"
    DELIVERED = "order.delivered"
    CANCELED = "order.canceled"


class AuthEvents:
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"


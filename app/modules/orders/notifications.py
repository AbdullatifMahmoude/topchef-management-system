from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class OrderNotificationPort(Protocol):
    async def enqueue(self, order: dict, event_type: str) -> bool: ...


class OutboxOrderNotifications:
    """Adapter that keeps the order domain independent from WhatsApp/Meta."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(self, order: dict, event_type: str) -> bool:
        from app.modules.settings.whatsapp_outbox import enqueue_order_notification

        return await enqueue_order_notification(self.db, order, event_type)

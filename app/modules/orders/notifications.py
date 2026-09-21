from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer.models import CustomerNotification


class OrderNotificationPort(Protocol):
    async def enqueue(self, order: dict, event_type: str) -> bool: ...


class AccountOrderNotifications:
    """Persist order updates in the registered customer's private account."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(self, order: dict, event_type: str) -> bool:
        customer_id = order.get("customer_id")
        if not customer_id or event_type not in {"created", "status_changed"}:
            return False
        status = str(order.get("order_status", "new"))
        status = status.rsplit(".", 1)[-1].lower()
        labels = {
            "new": ("تم استلام طلبك", "وصلنا طلبك وهنبدأ مراجعته حالًا."),
            "confirmed": ("تم تأكيد طلبك", "طلبك اتأكد وبيتم تجهيزه."),
            "preparing": ("طلبك بيتجهز", "المطبخ بدأ تجهيز طلبك."),
            "ready": ("طلبك جاهز", "طلبك جاهز للاستلام أو التسليم للمندوب."),
            "out_for_delivery": ("طلبك في الطريق", "المندوب خرج بطلبك للتوصيل."),
            "delivered": ("تم توصيل طلبك", "نتمنى تكون تجربتك عجبتك."),
            "completed": ("اكتمل طلبك", "تم إكمال الطلب بنجاح."),
            "cancelled": ("تم إلغاء الطلب", "تم إلغاء الطلب. تقدر تراجع تفاصيله من سجل الطلبات."),
        }
        title, message = labels.get(status, ("تحديث على طلبك", "حالة طلبك اتحدثت."))
        order_number = order.get("order_number") or order.get("id")
        event_key = f"order:{order['id']}:{event_type}:{status}"
        exists = await self.db.scalar(select(CustomerNotification.id).where(
            CustomerNotification.customer_id == customer_id,
            CustomerNotification.event_key == event_key,
        ))
        if exists:
            return False
        self.db.add(CustomerNotification(
            customer_id=customer_id,
            order_id=order["id"],
            event_key=event_key,
            title=title,
            message=f"طلب #{order_number}: {message}",
        ))
        return True

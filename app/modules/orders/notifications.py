from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer.loyalty import customer_points_balance, points_month_bounds
from app.modules.customer.models import CustomerNotification, CustomerPointLedger


class OrderNotificationPort(Protocol):
    async def enqueue(self, order: dict, event_type: str) -> bool: ...


class AccountOrderNotifications:
    """Persist order updates in the registered customer's private account."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(self, order: dict, event_type: str) -> bool:
        customer_id = order.get("customer_id")
        if not customer_id or event_type not in {"created", "status_changed", "updated"}:
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
        title, message = ("تم تعديل طلبك", "اتعدلت تفاصيل طلبك. تقدر تراجعها من سجل الطلبات.") if event_type == "updated" else labels.get(
            status, ("تحديث على طلبك", "حالة طلبك اتحدثت."),
        )
        order_number = order.get("order_number") or order.get("id")
        event_key = f"order:{order['id']}:{event_type}:{order.get('updated_at') or status}" if event_type == "updated" else f"order:{order['id']}:{event_type}:{status}"
        exists = await self.db.scalar(select(CustomerNotification.id).where(
            CustomerNotification.customer_id == customer_id,
            CustomerNotification.event_key == event_key,
        ))
        if exists:
            return False
        if status == "confirmed" or event_type == "updated":
            award = await self.db.scalar(select(CustomerPointLedger).where(
                CustomerPointLedger.order_id == order["id"],
                CustomerPointLedger.customer_id == customer_id,
                CustomerPointLedger.reversed_at.is_(None),
            ))
            if award:
                now = datetime.now(UTC)
                balance = await customer_points_balance(self.db, customer_id, now=now)
                start_utc, end_utc, _, _ = points_month_bounds(now)
                earned_this_month = start_utc.replace(tzinfo=None) <= award.created_at < end_utc.replace(tzinfo=None)
                if not earned_this_month:
                    message += " نقاط الطلب ده تخص شهر سابق وانتهت؛ ما بتضافش لرصيد الشهر الحالي."
                elif award.points == 0:
                    message += " الطلب ده ما حققش نقاط حسب قواعد الكسب الحالية."
                elif event_type == "updated":
                    message += f" نقاط الطلب بعد التعديل {award.points} نقطة، ورصيدك الحالي {balance} نقطة لهذا الشهر."
                else:
                    message += f" كسبت {award.points} نقطة من الطلب ده، وبقى معاك {balance} نقطة لهذا الشهر."
        elif event_type == "created" and status == "new":
            message += " نقاط الطلب هتتحسب بعد تأكيده."
        if event_type == "created" and order.get("loyalty_status") == "reserved":
            message += f" حجزنا {order.get('loyalty_points_spent', 0)} نقطة لمكافأة الطلب لحين تأكيده."
        if status == "cancelled" and order.get("loyalty_status") == "reversed":
            message += " ألغي استبدال نقاط الطلب؛ راجع رصيد الشهر الحالي في حسابك."
        self.db.add(CustomerNotification(
            customer_id=customer_id,
            order_id=order["id"],
            event_key=event_key,
            title=title,
            message=f"طلب #{order_number}: {message}",
        ))
        return True

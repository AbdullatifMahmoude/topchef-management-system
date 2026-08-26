import inspect

from app.modules.orders.service import OrderService


class FakeNotifications:
    def __init__(self):
        self.events = []

    async def enqueue(self, order: dict, event_type: str) -> bool:
        self.events.append((order, event_type))
        return True


def test_order_service_accepts_notification_port_without_whatsapp_dependency():
    fake = FakeNotifications()
    service = OrderService(
        db=object(), pricing_service=object(), offer_service=object(),
        notification_service=fake,
    )
    assert service.notifications is fake


def test_order_service_does_not_import_whatsapp_adapter_directly():
    source = inspect.getsource(OrderService)
    assert "whatsapp" not in source.lower()

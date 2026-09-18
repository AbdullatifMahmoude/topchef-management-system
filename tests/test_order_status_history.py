from types import SimpleNamespace

import pytest

from app.core.enums import OrderStatus
from app.modules.customer import models as customer_models  # noqa: F401
from app.modules.menu import models as menu_models  # noqa: F401
from app.modules.offer import models as offer_models  # noqa: F401
from app.modules.orders import models, schemas
from app.modules.orders.repository import OrderRepository


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_notes_only_update_does_not_create_status_history():
    db = FakeSession()
    repository = OrderRepository(db)
    order = SimpleNamespace(id=10, order_status=OrderStatus.CONFIRMED, internal_notes=None)

    await repository.update(order, schemas.OrderUpdate(internal_notes="ملاحظة"), changed_by_user_id=2)

    histories = [item for item in db.added if isinstance(item, models.OrderStatusHistory)]
    assert histories == []
    assert order.internal_notes == "ملاحظة"


@pytest.mark.asyncio
async def test_real_status_change_creates_one_history_record():
    db = FakeSession()
    repository = OrderRepository(db)
    order = SimpleNamespace(id=10, order_status=OrderStatus.CONFIRMED, internal_notes=None)

    await repository.update(
        order,
        schemas.OrderUpdate(order_status=OrderStatus.COMPLETED),
        changed_by_user_id=2,
    )

    histories = [item for item in db.added if isinstance(item, models.OrderStatusHistory)]
    assert len(histories) == 1
    assert histories[0].status == OrderStatus.COMPLETED

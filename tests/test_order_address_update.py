from types import SimpleNamespace

import pytest

from app.modules.orders import schemas
from app.modules.orders.repository import OrderRepository
from app.modules.orders.service import OrderService


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_full_update_applies_generated_address_id():
    db = FakeSession()
    repository = OrderRepository(db)
    old_address = SimpleNamespace(id=3, address="العنوان القديم")
    order = SimpleNamespace(address_id=3, address=old_address, updated_at=None)
    update = schemas.OrderUpdateFull(address_id=9, customer_address="العنوان الجديد")

    await repository.update_order_full(order, update)

    assert order.address_id == 9


def test_resolved_address_updates_foreign_key_and_loaded_relationship():
    old_address = SimpleNamespace(id=3, address="العنوان القديم")
    new_address = SimpleNamespace(id=9, address="العنوان الجديد")
    order = SimpleNamespace(address_id=3, address=old_address)
    update = schemas.OrderUpdateFull(customer_address="العنوان الجديد")

    OrderService._apply_resolved_address(order, update, new_address)

    assert update.address_id == 9
    assert order.address is new_address

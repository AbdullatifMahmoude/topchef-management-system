from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.enums import OrderSource, OrderStatus, OrderType
from app.core.exceptions import ValidationError
from app.modules.customer.models import Customer, CustomerAddress
from app.modules.orders import schemas
from app.modules.orders.models import Order
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


@pytest.mark.asyncio
@pytest.mark.parametrize("has_customer_snapshot,has_linked_customer", [
    (True, True), (False, True), (False, False),
])
async def test_address_edit_persists_or_rejects_missing_customer(
    monkeypatch, has_customer_snapshot, has_linked_customer,
):
    # Register the related ORM tables, then use an isolated database so the
    # assertion checks a fresh read rather than only the session identity map.
    import app.main  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            customer = Customer(name="Test Customer", phone_number="01000000001")
            db.add(customer)
            await db.flush()
            old_address = CustomerAddress(customer_id=customer.id, address="Old address")
            db.add(old_address)
            await db.flush()
            order = Order(
                order_number="TEST-ADDRESS-1",
                order_type=OrderType.DELIVERY,
                order_source=OrderSource.CASHIER,
                order_status=OrderStatus.NEW,
                customer_id=customer.id if has_linked_customer else None,
                customer_name=customer.name if has_customer_snapshot else None,
                customer_phone=customer.phone_number if has_customer_snapshot else None,
                address_id=old_address.id,
            )
            db.add(order)
            await db.commit()
            order_id = order.id

        monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
        async with sessions() as db:
            service = OrderService(
                db,
                pricing_service=AsyncMock(),
                offer_service=AsyncMock(),
                notification_service=AsyncMock(),
            )
            update = schemas.OrderUpdateFull(
                customer_name="Test Customer" if has_customer_snapshot else "",
                customer_phone="01000000001" if has_customer_snapshot else "",
                customer_address="New address",
            )
            if not has_linked_customer:
                with pytest.raises(ValidationError):
                    await service.update_order(order_id, update)
                return
            updated = await service.update_order(order_id, update)
            assert updated.customer_address == "New address"
            await db.commit()

        async with sessions() as db:
            stored = await db.scalar(select(Order).where(Order.id == order_id))
            assert stored is not None
            address = await db.get(CustomerAddress, stored.address_id)
            assert address is not None
            assert address.address == "New address"
    finally:
        await engine.dispose()

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - registers all ORM models before mapper configuration
from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.modules.customer import account_router
from app.modules.customer.models import CustomerNotification
from app.modules.orders.notifications import AccountOrderNotifications


class RecordingSession:
    def __init__(self, existing=None):
        self.added = []
        self.existing = existing

    def add(self, value):
        self.added.append(value)

    async def scalar(self, _query):
        return self.existing


@pytest.mark.asyncio
async def test_registered_customer_receives_private_order_notification():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "status_changed",
    )
    assert queued is True
    assert len(db.added) == 1
    assert db.added[0].customer_id == 7
    assert db.added[0].order_id == 12
    assert "0042" in db.added[0].message


@pytest.mark.asyncio
async def test_guest_order_does_not_create_account_notification():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": None, "order_number": "0042", "order_status": "new"},
        "created",
    )
    assert queued is False
    assert db.added == []


@pytest.mark.asyncio
async def test_non_status_edits_do_not_spam_customer():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "updated",
    )
    assert queued is False
    assert db.added == []


@pytest.mark.asyncio
async def test_duplicate_status_event_is_idempotent():
    db = RecordingSession(existing=99)
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "status_changed",
    )
    assert queued is False
    assert db.added == []


@pytest.mark.asyncio
async def test_customer_can_dismiss_only_their_own_notification():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            own = CustomerNotification(customer_id=7, order_id=12, event_key="order-12-confirmed",
                                       title="اتأكد الطلب", message="طلبك اتأكد")
            other = CustomerNotification(customer_id=8, order_id=13, event_key="order-13-confirmed",
                                         title="اتأكد الطلب", message="طلبك اتأكد")
            db.add_all([own, other])
            await db.commit()

            before = await account_router.customer_notifications(payload={"customer_id": 7}, db=db)
            assert [item.id for item in before.notifications] == [own.id]
            assert before.unread_count == 1

            with pytest.raises(NotFoundError):
                await account_router.dismiss_customer_notification(other.id, payload={"customer_id": 7}, db=db)
            assert other.dismissed_at is None

            await account_router.dismiss_customer_notification(own.id, payload={"customer_id": 7}, db=db)
            assert own.dismissed_at is not None
            assert own.event_key == "order-12-confirmed"
            after = await account_router.customer_notifications(payload={"customer_id": 7}, db=db)
            assert after.notifications == []
            assert after.unread_count == 0
            await account_router.read_customer_notifications(payload={"customer_id": 7}, db=db)
            assert own.is_read is False
            assert other.dismissed_at is None
            with pytest.raises(NotFoundError):
                await account_router.dismiss_customer_notification(own.id, payload={"customer_id": 7}, db=db)
    finally:
        await engine.dispose()


def test_notification_dismissal_migration_adds_and_removes_column(monkeypatch):
    path = Path("alembic/versions/a92726_customer_notification_dismissal.py")
    spec = importlib.util.spec_from_file_location("customer_notification_dismissal", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE customer_notifications (id INTEGER PRIMARY KEY)")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert "dismissed_at" in {column["name"] for column in inspect(connection).get_columns("customer_notifications")}
            migration.downgrade()
            assert "dismissed_at" not in {column["name"] for column in inspect(connection).get_columns("customer_notifications")}
    finally:
        engine.dispose()

import enum
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    Index,
    Date,
    UniqueConstraint,
    Sequence,
)
from app.core.enums import OrderStatus, OrderType, OrderSource
from sqlalchemy.orm import relationship

from app.core.database import Base, DbEnum
from app.modules.users.models import User

# Atomic sequence for order numbering (PostgreSQL)
order_number_seq = Sequence('order_number_seq', start=1)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(20), nullable=False)
    order_date = Column(Date, default=date.today, nullable=False)
    idempotency_key = Column(String(100), nullable=True, index=True) # Remove unique=True
    
    # Customer Info: Supports both registered customers or guest phone/name
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer_phone = Column(String(20), nullable=True)
    customer_name = Column(String(100), nullable=True)
    
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    delivery_person_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    address_id = Column(Integer, ForeignKey("customer_addresses.id"), nullable=True, index=True)
    
    order_type = Column(
        DbEnum(OrderType, name="ordertype"),
        nullable=False,
    )
    order_status = Column(
        DbEnum(OrderStatus, name="orderstatus"),
        nullable=False,
        default=OrderStatus.NEW,
    )
    order_source = Column(
        DbEnum(OrderSource, name="ordersource"),
        nullable=False,
    )
    
    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    delivery_fee = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    
    customer_notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None))

    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    creator = relationship("User", foreign_keys=[created_by_user_id])
    delivery_person = relationship("User", foreign_keys=[delivery_person_id])
    address = relationship("CustomerAddress", foreign_keys=[address_id])

    @property
    def creator_name(self) -> str:
        if self.creator:
            return self.creator.full_name or self.creator.username
        return "Unknown"

    @property
    def delivery_person_name(self) -> str:
        if self.delivery_person:
            return self.delivery_person.full_name or self.delivery_person.username
        return "Unknown"

    __table_args__ = (
        UniqueConstraint('idempotency_key', 'order_date', name='uq_idempotency_per_day'),
        Index('idx_order_status', 'order_status'),
        Index('idx_order_type', 'order_type'),
        Index('idx_order_source', 'order_source'),
        Index('idx_order_created', 'created_at'),
        Index('idx_order_number_date', 'order_number', 'order_date', unique=True),
        Index('idx_order_date_source', 'order_date', 'order_source'),
    )


    def can_transition_to(self, new_status: OrderStatus) -> bool:
        """Domain logic for state transitions."""
        allowed_transitions = {
            OrderStatus.NEW: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
            OrderStatus.CONFIRMED: [OrderStatus.COMPLETED, OrderStatus.DELIVERED, OrderStatus.CANCELLED],
            OrderStatus.DELIVERED: [],
            OrderStatus.COMPLETED: [],
            OrderStatus.CANCELLED: []
        }
        return new_status in allowed_transitions.get(self.order_status, [])


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10,2), nullable=False)
    total_price = Column(Numeric(10,2), nullable=False)

    order = relationship("Order", back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    # This table uses the same enum as orders
    status = Column(DbEnum(OrderStatus, name="order_status"), nullable=False)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    order = relationship("Order", backref="status_history")

class OutboxEventStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(100), nullable=False) # e.g. "ORDER_CREATED"
    topic = Column(String(100), nullable=False)      # e.g. "orders.cashier"
    payload = Column(Text, nullable=False)           # JSON string payload
    status = Column(
        DbEnum(OutboxEventStatus, name="outbox_event_status"),
        default=OutboxEventStatus.PENDING,
        nullable=False
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)
    processed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index('idx_outbox_status', 'status'),
    )

class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(100), nullable=False)
    event_id = Column(Integer, nullable=False)
    processed_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)

    __table_args__ = (
        UniqueConstraint('device_id', 'event_id', name='uq_device_event'),
    )

class ActiveDevice(Base):
    __tablename__ = "active_devices"
    device_id = Column(String(100), primary_key=True)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None))
    version = Column(String(20), nullable=True)
    ip_address = Column(String(50), nullable=True)

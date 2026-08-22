from datetime import date, datetime, timezone, timedelta

from typing import Optional
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
    Boolean,
)
from app.core.enums import OrderStatus, OrderType, OrderSource, DiscountType, PaymentMethod
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
    payment_method = Column(
        DbEnum(PaymentMethod, name="paymentmethod"),
        nullable=False,
        default=PaymentMethod.CASH,
        server_default="CASH",
    )
    
    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    discount_type = Column(DbEnum(DiscountType, name="discounttype"), nullable=True)
    discount_value = Column(Numeric(10, 2), nullable=True)  # raw value entered by cashier
    discount_reason = Column(String(255), nullable=True)
    delivery_fee = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    
    customer_notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
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
    offer_usage = relationship(
        "OfferUsage",
        primaryjoin="Order.id == foreign(OfferUsage.order_id)",
        uselist=False,
        viewonly=True,
    )

    @property
    def creator_name(self) -> Optional[str]:
        if self.creator:
            return self.creator.full_name or self.creator.username
        return None

    @property
    def delivery_person_name(self) -> Optional[str]:
        if self.delivery_person:
            return self.delivery_person.full_name or self.delivery_person.username
        return None

    @property
    def customer_address(self) -> Optional[str]:
        if self.address:
            return self.address.address
        return None

    @property
    def applied_offer(self):
        usage = self.offer_usage
        if not usage or not usage.offer:
            return None
        offer = usage.offer
        return {
            "code": offer.code,
            "display_name": offer.display_name,
            "discount_type": offer.discount_type,
            "discount_value": offer.discount_value,
            "discount_amount": usage.discount_amount,
        }

    __table_args__ = (
        UniqueConstraint('idempotency_key', 'order_date', name='uq_idempotency_per_day'),
        Index('idx_order_status', 'order_status'),
        Index('idx_order_type', 'order_type'),
        Index('idx_order_source', 'order_source'),
        Index('idx_order_payment_method', 'payment_method'),
        Index('idx_order_created', 'created_at'),
        Index('idx_order_number_date', 'order_number', 'order_date', unique=True),
        Index('idx_order_date_source', 'order_date', 'order_source'),
        Index('idx_order_date_created_at', 'order_date', 'created_at'),
        # Index مخصوص للتقارير - بيسرع الـ aggregation بتاعة الشهري والسنوي
        Index('idx_order_date_status', 'order_date', 'order_status'),
    )


    def can_transition_to(self, new_status: OrderStatus) -> bool:
        """Domain logic for state transitions."""
        allowed_transitions = {
            OrderStatus.NEW: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
            OrderStatus.CONFIRMED: [OrderStatus.COMPLETED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED, OrderStatus.CANCELLED],
            OrderStatus.OUT_FOR_DELIVERY: [OrderStatus.DELIVERED, OrderStatus.CANCELLED],
            OrderStatus.DELIVERED: [],
            OrderStatus.COMPLETED: [],
            OrderStatus.CANCELLED: []
        }
        return new_status in allowed_transitions.get(self.order_status, [])


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10,2), nullable=False)
    total_price = Column(Numeric(10,2), nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None))

    order = relationship("Order", back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    # This table uses the same enum as orders
    status = Column(DbEnum(OrderStatus, name="orderstatus"), nullable=False)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None))

    order = relationship("Order", backref="status_history")

class OrderModificationHistory(Base):
    __tablename__ = "order_modification_history"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None), nullable=False)
    
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON
    # We will use JSON to store the modifications array
    changes = Column(JSON().with_variant(JSONB, 'postgresql'), nullable=False)

    order = relationship("Order", backref="modifications")
    changed_by = relationship("User", foreign_keys=[changed_by_user_id])

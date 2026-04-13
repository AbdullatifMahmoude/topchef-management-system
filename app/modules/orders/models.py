import enum
from datetime import date, datetime

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
)
from app.core.enums import OrderStatus
from sqlalchemy.orm import relationship

from app.core.database import Base



class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(20), nullable=False)
    order_date = Column(Date, default=date.today, nullable=False)
    idempotency_key = Column(String(100), unique=True,
                             nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    delivery_person_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    address_id = Column(Integer, ForeignKey(
        "customer_addresses.id"), nullable=True)
    order_type = Column(SQLEnum(OrderType, name="order_type", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    order_status = Column(SQLEnum(OrderStatus, name="order_status", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    order_source = Column(SQLEnum(OrderSource, name="order_source", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    customer_notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    items = relationship(
        "orderitem",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index('idx_order_status', 'order_status'),
        Index('idx_order_type', 'order_type'),
        Index('idx_order_source', 'order_source'),
        Index('idx_order_created', 'created_at'),
        Index('idx_order_number_date', 'order_number', 'order_date', unique=True)
    )


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
    status = Column(SQLEnum(OrderStatus, name="order_status", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    order = relationship("Order", backref="status_history")

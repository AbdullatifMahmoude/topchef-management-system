import enum
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Enum,
    Text,
    Index,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class OrderStatus(str, enum.Enum):
    NEW = "جديد"
    CONFIRMED = "مؤكد"
    COMPLETED = "اكتمل"
    DELIVERED = "وصل"
    CANCELED = "اتلغى"


class OrderType(str, enum.Enum):
    HALL = "صالة"
    TAKEAWAY = "تيك اواي"
    DELIVERY = "ديليفري"
    ONLINE = "أونلاين"


class OrderSource(str, enum.Enum):
    CASHIER = "كاشير"
    ONLINE = "أونلاين"


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
    order_type = Column(Enum(OrderType), nullable=False)
    order_status = Column(Enum(OrderStatus), nullable=False)
    order_source = Column(Enum(OrderSource), nullable=False)
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

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(40), unique=True, index=True, nullable=False)
    email = Column(String(254), unique=True, index=True, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    pin_hash = Column(String(255), nullable=True)
    account_activated_at = Column(DateTime, nullable=True)
    whatsapp_status = Column(String(20), nullable=False, default="unknown", server_default="unknown")
    whatsapp_consent_at = Column(DateTime, nullable=True)
    whatsapp_checked_at = Column(DateTime, nullable=True)
    whatsapp_failure_reason = Column(String(255), nullable=True)

    addresses = relationship("CustomerAddress", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")

class CustomerAddress(Base):
    __tablename__ = "customer_addresses"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    address = Column(String(255), nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="addresses")


class CustomerDevice(Base):
    __tablename__ = "customer_devices"

    id = Column(String(36), primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    device_name = Column(String(120), nullable=False, default="جهاز")
    expires_at = Column(DateTime, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CustomerNotification(Base):
    __tablename__ = "customer_notifications"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    event_key = Column(String(120), nullable=False)
    title = Column(String(120), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("customer_id", "event_key", name="uq_customer_notification_event"),
    )

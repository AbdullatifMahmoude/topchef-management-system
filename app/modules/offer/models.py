from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SA_Enum, Numeric, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base, DbEnum
from app.core.enums import DiscountType

class Offer(Base):
    __tablename__ = "offers"

    offer_id = Column(Integer, primary_key=True, index=True)
    code = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(255), nullable=True)
    discount_type = Column(
        DbEnum(DiscountType, name="discount_type"),
        nullable=False,
    )
    discount_value = Column(Numeric(10, 2), nullable=False)
    min_order_amount = Column(Numeric(10, 2), nullable=True) # Changed to Numeric for consistency
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    max_discount_amount = Column(Numeric(10, 2), nullable=True)
    usage_limit = Column(Integer, nullable=True)
    usage_per_user = Column(Integer, nullable=True)
    current_usage = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    valid_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    valid_to = Column(DateTime, nullable=False)
    # NOTE: Version column kept for potential future optimistic locking
    # Currently using pessimistic locking (SELECT FOR UPDATE) in apply_offer()
    # which is safer for high-concurrency scenarios.
    version = Column(Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        "version_id_col": version
    }

    usages = relationship("OfferUsage", back_populates="offer", cascade="all, delete-orphan")

    def is_started(self):
        return datetime.utcnow() >= self.valid_from

    def is_expired(self):
        return datetime.utcnow() > self.valid_to

    def is_usage_limit_reached(self) -> bool:
        return self.usage_limit is not None and self.current_usage >= self.usage_limit

    def deactivate_if_expired(self):
        if self.is_expired() and self.is_active:
            self.is_active = False
            return True
        return False

    def deactivate_if_usage_full(self) -> bool:
        if self.is_usage_limit_reached() and self.is_active:
            self.is_active = False
            return True
        return False

    def update_info(self, update_data: dict):
        for key, value in update_data.items():
            if hasattr(self, key):
                setattr(self, key, value)

class OfferUsage(Base):
    __tablename__ = "offer_usages"

    usage_id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(Integer, ForeignKey("offers.offer_id"), nullable=False, index=True)
    customer_phone = Column(String(255), nullable=True, index=True)
    cashier_id = Column(Integer, nullable=True, index=True)
    order_id = Column(Integer, nullable=True) 
    applied_at = Column(DateTime, default=datetime.utcnow)
    discount_amount = Column(Numeric(10, 2), nullable=False)

    offer = relationship("Offer", back_populates="usages")

    __table_args__ = (
        Index('idx_offer_customer', 'offer_id', 'customer_phone'),
        UniqueConstraint('offer_id', 'customer_phone', name='uq_offer_customer_usage'),
    )

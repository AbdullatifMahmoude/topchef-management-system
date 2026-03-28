from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Enum as SA_Enum
from datetime import datetime
from app.core.database import Base
from app.core.enums import DiscountType

class Offer(Base):
    __tablename__ = "offers"

    offer_id = Column(Integer, primary_key=True, index=True)
    code = Column(String(255), nullable=False, unique=True)
    discount_type = Column(SA_Enum(DiscountType), nullable=False)
    discount_value = Column(Numeric(10, 2), nullable=False)
    min_order_amount = Column(Integer, nullable=True)
    max_discount_amount = Column(Integer, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    usage_per_user = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    valid_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    valid_to = Column(DateTime, nullable=False)

    def is_expired(self):
        return datetime.utcnow() > self.valid_to

    def deactivate_if_expired(self):
        if self.is_expired() and self.is_active:
            self.is_active = False
            return True
        return False

    def update_info(self, update_data: dict):
        for key, value in update_data.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self

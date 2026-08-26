from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey
from app.core.database import Base
from datetime import datetime

class AppSetting(Base):
    __tablename__ = "app_settings"
    
    key = Column(String(100), primary_key=True)
    value_bool = Column(Boolean, default=True)
    value_text = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WhatsAppOutbox(Base):
    __tablename__ = "whatsapp_outbox"

    id = Column(Integer, primary_key=True)
    event_key = Column(String(64), nullable=False, unique=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    phone = Column(String(20), nullable=False)
    template_name = Column(String(512), nullable=False)
    message_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

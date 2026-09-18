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
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    phone = Column(String(20), nullable=False)
    template_name = Column(String(512), nullable=False)
    message_text = Column(Text, nullable=False)
    template_parameters = Column(Text, nullable=True)
    button_payloads = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    meta_message_id = Column(String(255), nullable=True, unique=True, index=True)
    delivery_status = Column(String(20), nullable=True)
    delivery_updated_at = Column(DateTime, nullable=True)
    delivery_error = Column(Text, nullable=True)
    message_type = Column(String(20), nullable=False, default="template", server_default="template")
    interactive_payload = Column(Text, nullable=True)
    service_window_expires_at = Column(DateTime, nullable=True)
    subscription_id = Column(Integer, ForeignKey("whatsapp_order_subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    skip_reason = Column(String(255), nullable=True)


class WhatsAppOrderSubscription(Base):
    __tablename__ = "whatsapp_order_subscriptions"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    whatsapp_phone = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    activated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_customer_message_at = Column(DateTime, nullable=False)
    service_window_expires_at = Column(DateTime, nullable=False, index=True)
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WhatsAppInboundMessage(Base):
    __tablename__ = "whatsapp_inbound_messages"

    id = Column(Integer, primary_key=True)
    meta_message_id = Column(String(255), nullable=False, unique=True, index=True)
    whatsapp_phone = Column(String(20), nullable=False, index=True)
    message_type = Column(String(30), nullable=False)
    text = Column(Text, nullable=True)
    button_payload = Column(String(255), nullable=True)
    received_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    processing_result = Column(String(255), nullable=True)


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"

    whatsapp_phone = Column(String(20), primary_key=True)
    state = Column(String(50), nullable=False, default="idle", server_default="idle")
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

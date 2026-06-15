from sqlalchemy import Column, String, Boolean, DateTime
from app.core.database import Base
from datetime import datetime

class AppSetting(Base):
    __tablename__ = "app_settings"
    
    key = Column(String(100), primary_key=True)
    value_bool = Column(Boolean, default=True)
    description = Column(String(255), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

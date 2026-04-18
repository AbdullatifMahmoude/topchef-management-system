from sqlalchemy import Column, String, Boolean
from app.core.database import Base

class AppSetting(Base):
    __tablename__ = "app_settings"
    
    key = Column(String(100), primary_key=True)
    value_bool = Column(Boolean, default=True)
    description = Column(String(255), nullable=True)

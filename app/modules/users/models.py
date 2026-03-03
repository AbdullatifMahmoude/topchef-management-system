from app.core.database import Base
from app.core.enums import UserRole
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Index,
    Enum as SQLEnum,
    Boolean
)
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(200), unique=True, nullable= False)
    role = Column(SQLEnum(UserRole, name="user_role"),nullable=False)
    phone = Column(String(15),nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_users_role", "role"),
        )
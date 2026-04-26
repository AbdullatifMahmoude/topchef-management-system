from app.core.database import Base, DbEnum
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
    full_name = Column(String(200), nullable=True)
    role = Column(
        DbEnum(UserRole, name="user_role"),
        nullable=False,
    )
    phone = Column(String(15),nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_users_role", "role"),
        )

    def set_password(self, password: str):
        from app.core.security import get_password_hash
        self.hashed_password = get_password_hash(password)

    def check_password(self, password: str) -> bool:
        from app.core.security import verify_password
        return verify_password(password, self.hashed_password)

    def toggle_active(self):
        self.is_active = not self.is_active
        return self.is_active

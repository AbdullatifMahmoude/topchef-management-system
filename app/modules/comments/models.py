from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False, index=True)
    stars = Column(Integer, nullable=False)  # 1-5
    comment_text = Column(Text, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(
        DateTime, 
        default=lambda: datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None),
        nullable=False
    )

    __table_args__ = (
        Index('idx_comment_created', 'created_at'),
        Index('idx_comment_stars', 'stars'),
    )

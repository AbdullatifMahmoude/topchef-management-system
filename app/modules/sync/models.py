"""Sync quarantine — persistently failing reconciliation rows."""

from datetime import datetime, timezone, timedelta

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, Index

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)


class SyncQuarantine(Base):
    """Rows that fail reconciliation repeatedly are quarantined here for visibility."""

    __tablename__ = "sync_quarantine"

    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String(100), nullable=False, index=True)
    record_key = Column(String(255), nullable=False, index=True)
    row_payload = Column(Text, nullable=True)
    error_message = Column(Text, nullable=False)
    failure_count = Column(Integer, default=1, nullable=False)
    first_failed_at = Column(DateTime, default=_now, nullable=False)
    last_failed_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    quarantined = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_sync_quarantine_lookup", "table_name", "record_key", unique=True),
    )

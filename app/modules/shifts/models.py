from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CashierShift(Base):
    __tablename__ = "cashier_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    cash_tracking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    cash_expenses: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    actual_closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    closing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Closing/reopening a shift updates this timestamp.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )
    
    # Optional metadata or computed stats stored here if we wanted to denormalize, 
    # but we can also just compute dynamically in the API.
    
    user = relationship("User", backref="shifts")


class ShiftExpense(Base):
    __tablename__ = "shift_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # New admin expenses are linked to the selected cashier shift. Older
    # day-wide admin expenses may still have no shift.
    shift_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cashier_shifts.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    paid_from: Mapped[str] = mapped_column(String(20), nullable=False, default="legacy_unverified", server_default="legacy_unverified")
    receipt_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    shift = relationship("CashierShift", backref="expenses")
    user = relationship("User")


class ShiftCashAddition(Base):
    __tablename__ = "shift_cash_additions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shift_id: Mapped[int] = mapped_column(Integer, ForeignKey("cashier_shifts.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False)

    shift = relationship("CashierShift", backref="cash_additions")
    admin = relationship("User")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_shift_cash_additions_positive_amount"),
    )


class OrderCashMovement(Base):
    """An append-only record of restaurant-owned cash changing hands."""

    __tablename__ = "order_cash_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    shift_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cashier_shifts.id", ondelete="RESTRICT"), index=True)
    rider_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    from_holder: Mapped[str] = mapped_column(String(16), nullable=False)
    to_holder: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    reversal_of_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("order_cash_movements.id", ondelete="RESTRICT"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_order_cash_movements_positive"),
        CheckConstraint("from_holder <> to_holder", name="ck_order_cash_movements_distinct_holders"),
    )


class ShiftCloseSnapshot(Base):
    """The figures visible at close; later corrections never rewrite them."""

    __tablename__ = "shift_close_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(Integer, ForeignKey("cashier_shifts.id", ondelete="RESTRICT"), nullable=False, unique=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    confirmed_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unconfirmed_cash_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cash_expenses: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cashier_count: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    difference: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    admin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"))
    admin_count: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_note: Mapped[str | None] = mapped_column(String(500))


class ShiftCashAdjustment(Base):
    """Audited post-close cash correction, separate from the frozen snapshot."""

    __tablename__ = "shift_cash_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(Integer, ForeignKey("cashier_shifts.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("amount <> 0", name="ck_shift_cash_adjustments_nonzero"),)

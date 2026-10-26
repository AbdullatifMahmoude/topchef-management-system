"""Record cash custody and immutable shift close snapshots.

Revision ID: a102626cashcustody
Revises: a102526orderisprinted
"""

from alembic import op
import sqlalchemy as sa

revision = "a102626cashcustody"
down_revision = "a102526orderisprinted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cashier_shifts", sa.Column("cash_tracking_enabled", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("shift_expenses", sa.Column("paid_from", sa.String(20), nullable=False, server_default="legacy_unverified"))
    op.add_column("shift_expenses", sa.Column("receipt_reference", sa.String(200), nullable=True))
    op.create_table(
        "order_cash_movements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("cashier_shifts.id", ondelete="RESTRICT")),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_holder", sa.String(16), nullable=False),
        sa.Column("to_holder", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("reversal_of_id", sa.Integer, sa.ForeignKey("order_cash_movements.id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_order_cash_movements_positive"),
        sa.CheckConstraint("from_holder <> to_holder", name="ck_order_cash_movements_distinct_holders"),
    )
    op.create_index("ix_order_cash_movements_order_id", "order_cash_movements", ["order_id"])
    op.create_index("ix_order_cash_movements_shift_id", "order_cash_movements", ["shift_id"])
    op.create_index("ix_order_cash_movements_rider_id", "order_cash_movements", ["rider_id"])
    op.create_table(
        "shift_close_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("cashier_shifts.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("opening_cash", sa.Numeric(12, 2), nullable=False),
        sa.Column("confirmed_cash", sa.Numeric(12, 2), nullable=False),
        sa.Column("unconfirmed_cash_sales", sa.Numeric(12, 2), nullable=False),
        sa.Column("cash_expenses", sa.Numeric(12, 2), nullable=False),
        sa.Column("expected_cash", sa.Numeric(12, 2), nullable=False),
        sa.Column("cashier_count", sa.Numeric(12, 2)),
        sa.Column("difference", sa.Numeric(12, 2)),
        sa.Column("admin_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("admin_count", sa.Numeric(12, 2)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmation_note", sa.String(500)),
    )
    op.create_table(
        "shift_cash_adjustments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("cashier_shifts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount <> 0", name="ck_shift_cash_adjustments_nonzero"),
    )
    op.create_index("ix_shift_cash_adjustments_shift_id", "shift_cash_adjustments", ["shift_id"])


def downgrade() -> None:
    op.drop_index("ix_shift_cash_adjustments_shift_id", table_name="shift_cash_adjustments")
    op.drop_table("shift_cash_adjustments")
    op.drop_table("shift_close_snapshots")
    op.drop_index("ix_order_cash_movements_rider_id", table_name="order_cash_movements")
    op.drop_index("ix_order_cash_movements_shift_id", table_name="order_cash_movements")
    op.drop_index("ix_order_cash_movements_order_id", table_name="order_cash_movements")
    op.drop_table("order_cash_movements")
    op.drop_column("shift_expenses", "receipt_reference")
    op.drop_column("shift_expenses", "paid_from")
    op.drop_column("cashier_shifts", "cash_tracking_enabled")

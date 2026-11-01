"""Add phone reservations and cashier cancellation approval requests.

Revision ID: a102326phonecancel
Revises: a93026productdaily
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a102326phonecancel"
down_revision: str | None = "a93026productdaily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE ordertype ADD VALUE IF NOT EXISTS 'PHONE_RESERVATION'")

    op.create_table(
        "order_cancellation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_order_cancellation_status"),
    )
    op.create_index("ix_order_cancellation_requests_order_id", "order_cancellation_requests", ["order_id"])
    op.create_index(
        "uq_order_pending_cancellation", "order_cancellation_requests", ["order_id"], unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_order_pending_cancellation", table_name="order_cancellation_requests")
    op.drop_index("ix_order_cancellation_requests_order_id", table_name="order_cancellation_requests")
    op.drop_table("order_cancellation_requests")
    # PostgreSQL enum values are retained to avoid invalidating existing rows.

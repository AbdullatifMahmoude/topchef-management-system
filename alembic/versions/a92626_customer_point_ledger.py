"""Add a one-award-per-order customer points ledger.

Revision ID: a92626points
Revises: a92326transfer
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92626points"
down_revision: str | None = "a92326transfer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_point_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("eligible_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("rules_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("order_id", name="uq_customer_point_ledger_order_id"),
        sa.CheckConstraint("points >= 0", name="ck_customer_point_ledger_points_nonnegative"),
        sa.CheckConstraint("eligible_amount >= 0", name="ck_customer_point_ledger_eligible_amount"),
    )
    op.create_index("ix_customer_point_ledger_customer_id", "customer_point_ledger", ["customer_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE customer_point_ledger ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON customer_point_ledger FROM anon, authenticated")


def downgrade() -> None:
    op.drop_table("customer_point_ledger")

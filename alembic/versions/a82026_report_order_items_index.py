"""add order items index for report aggregations

Revision ID: a82026reportidx
Revises: cf513856aab0
Create Date: 2026-08-20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a82026reportidx"
down_revision: Union[str, None] = "cf513856aab0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"], unique=False)
    op.create_index("idx_order_date_created_at", "orders", ["order_date", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_order_date_created_at", table_name="orders")
    op.drop_index("ix_order_items_order_id", table_name="order_items")

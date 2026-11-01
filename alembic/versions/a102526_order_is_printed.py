"""Add is_printed tracking to orders.

Revision ID: a102526orderisprinted
Revises: a102326phonecancel
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a102526orderisprinted"
down_revision: str | None = "a102326phonecancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("is_printed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("idx_order_is_printed", "orders", ["is_printed"])


def downgrade() -> None:
    op.drop_index("idx_order_is_printed", table_name="orders")
    op.drop_column("orders", "is_printed")

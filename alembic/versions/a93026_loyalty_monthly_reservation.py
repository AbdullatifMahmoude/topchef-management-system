"""Keep the timestamp of a points reservation separate from order creation.

Revision ID: a93026loyaltymonth
Revises: a92726custdismiss
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a93026loyaltymonth"
down_revision: str | None = "a92726custdismiss"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("loyalty_reserved_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "loyalty_reserved_at")

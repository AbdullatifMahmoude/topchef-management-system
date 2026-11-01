"""Allow customers to dismiss notifications without losing event deduplication.

Revision ID: a92726custdismiss
Revises: a92626redeem
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92726custdismiss"
down_revision: str | None = "a92626redeem"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer_notifications", sa.Column("dismissed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_notifications", "dismissed_at")

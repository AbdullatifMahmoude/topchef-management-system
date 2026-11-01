"""Add a temporary, business-day scoped product availability deadline.

Revision ID: a93026productdaily
Revises: a93026loyaltymonth
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a93026productdaily"
down_revision: str | None = "a93026loyaltymonth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("temporary_unavailable_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "temporary_unavailable_until")

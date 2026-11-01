"""add unique customer email for email verification

Revision ID: a92126customeremail
Revises: a92126adminexpenses
Create Date: 2026-09-21
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92126customeremail"
down_revision: str | None = "a92126adminexpenses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("email", sa.String(254), nullable=True))
    op.create_index("ix_customers_email", "customers", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_column("customers", "email")

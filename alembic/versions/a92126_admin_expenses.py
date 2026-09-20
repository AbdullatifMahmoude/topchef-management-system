"""allow admin expenses without a cashier shift

Revision ID: a92126adminexpenses
Revises: a91826wainbound
Create Date: 2026-09-21
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92126adminexpenses"
down_revision: str | None = "a91826wainbound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("shift_expenses", "shift_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM shift_expenses WHERE shift_id IS NULL")
    op.alter_column("shift_expenses", "shift_id", existing_type=sa.Integer(), nullable=False)

"""add audited admin cash additions to cashier shifts

Revision ID: a91626shiftcashadd
Revises: a91426waconsent
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a91626shiftcashadd"
down_revision: Union[str, None] = "a91426waconsent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_cash_additions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_shift_cash_additions_positive_amount"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["cashier_shifts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shift_cash_additions_id", "shift_cash_additions", ["id"])
    op.create_index("ix_shift_cash_additions_shift_id", "shift_cash_additions", ["shift_id"])
    op.create_index("ix_shift_cash_additions_admin_id", "shift_cash_additions", ["admin_id"])


def downgrade() -> None:
    op.drop_index("ix_shift_cash_additions_admin_id", table_name="shift_cash_additions")
    op.drop_index("ix_shift_cash_additions_shift_id", table_name="shift_cash_additions")
    op.drop_index("ix_shift_cash_additions_id", table_name="shift_cash_additions")
    op.drop_table("shift_cash_additions")

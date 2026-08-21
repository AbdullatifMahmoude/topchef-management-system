"""add itemized cashier shift expenses

Revision ID: a82026expenses
Revises: a82026deliveryops
Create Date: 2026-08-20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a82026expenses"
down_revision: Union[str, None] = "a82026deliveryops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "shift_expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["shift_id"], ["cashier_shifts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shift_expenses_id", "shift_expenses", ["id"])
    op.create_index("ix_shift_expenses_shift_id", "shift_expenses", ["shift_id"])
    op.create_index("ix_shift_expenses_user_id", "shift_expenses", ["user_id"])
    op.create_index("ix_shift_expenses_target_date", "shift_expenses", ["target_date"])

def downgrade() -> None:
    op.drop_index("ix_shift_expenses_target_date", table_name="shift_expenses")
    op.drop_index("ix_shift_expenses_user_id", table_name="shift_expenses")
    op.drop_index("ix_shift_expenses_shift_id", table_name="shift_expenses")
    op.drop_index("ix_shift_expenses_id", table_name="shift_expenses")
    op.drop_table("shift_expenses")

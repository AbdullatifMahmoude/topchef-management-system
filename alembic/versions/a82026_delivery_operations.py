"""add out-for-delivery order status

Revision ID: a82026deliveryops
Revises: a82026productlogs
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a82026deliveryops"
down_revision: Union[str, None] = "a82026productlogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'OUT_FOR_DELIVERY' AFTER 'CONFIRMED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely while rows may use them.
    pass

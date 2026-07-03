"""Add discount_type discount_value discount_reason to orders

Revision ID: c57a61e06484
Revises: 2c39ca918760
Create Date: 2026-07-03 19:56:45.783108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c57a61e06484'
down_revision: Union[str, Sequence[str], None] = '2c39ca918760'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('discount_type', sa.String(length=20), nullable=True))
    op.add_column('orders', sa.Column('discount_value', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('orders', sa.Column('discount_reason', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'discount_reason')
    op.drop_column('orders', 'discount_value')
    op.drop_column('orders', 'discount_type')


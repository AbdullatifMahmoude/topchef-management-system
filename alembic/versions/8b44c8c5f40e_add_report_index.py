"""add_report_index

Revision ID: 8b44c8c5f40e
Revises: 19c7dd1df5fb
Create Date: 2026-07-12 03:20:31.917268

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8b44c8c5f40e'
down_revision: Union[str, Sequence[str], None] = '19c7dd1df5fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Index مخصوص للتقارير - بيسرع الـ aggregation بتاعة الشهري والسنوي
    op.create_index('idx_order_date_status', 'orders', ['order_date', 'order_status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_order_date_status', table_name='orders')

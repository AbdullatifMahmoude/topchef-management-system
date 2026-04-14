"""critical_fixes_p0_final

Revision ID: 6ac23eb1f0f0
Revises: 9ae20d01ff00
Create Date: 2026-04-14 20:42:27.771882

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ac23eb1f0f0'
down_revision: Union[str, Sequence[str], None] = '9ae20d01ff00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create sequence for order numbers
    op.execute("CREATE SEQUENCE order_number_seq;")
    
    # 2. Add performance indexes
    op.create_index('idx_order_customer_phone', 'orders', ['customer_phone'])
    op.create_index('idx_order_date_status', 'orders', ['order_date', 'order_status'])
    op.create_index('idx_offer_active', 'offers', ['is_active'])
    op.create_index('idx_offer_valid_dates', 'offers', ['valid_from', 'valid_to'])


def downgrade() -> None:
    op.drop_index('idx_offer_valid_dates', table_name='offers')
    op.drop_index('idx_offer_active', table_name='offers')
    op.drop_index('idx_order_date_status', table_name='orders')
    op.drop_index('idx_order_customer_phone', table_name='orders')
    
    op.execute("DROP SEQUENCE order_number_seq;")

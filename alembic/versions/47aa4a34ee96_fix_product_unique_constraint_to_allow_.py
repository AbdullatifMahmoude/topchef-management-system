"""Fix product unique constraint to allow same name in different categories

Revision ID: 47aa4a34ee96
Revises: 39cca0e95f22
Create Date: 2026-05-06 02:19:35.411484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47aa4a34ee96'
down_revision: Union[str, Sequence[str], None] = '39cca0e95f22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop the old strict unique constraint that was causing the error
    # We use execute to handle the 'IF EXISTS' safely in Postgres
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_product_name_key")
    
    # 2. Drop the composite one if it existed under a different name or to reset it
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS uq_product_name_cat_id")
    
    # 3. Create the correct composite unique constraint
    op.create_unique_constraint(
        'uq_product_name_cat_id', 
        'products', 
        ['product_name', 'cat_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_product_name_cat_id', 'products', type_='unique')
    op.create_unique_constraint('products_product_name_key', 'products', ['product_name'])

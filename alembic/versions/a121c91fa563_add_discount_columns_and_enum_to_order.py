"""Add discount columns and enum to order

Revision ID: a121c91fa563
Revises: c57a61e06484
Create Date: 2026-07-03 20:27:32.887439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import app

# revision identifiers, used by Alembic.
revision: str = 'a121c91fa563'
down_revision: Union[str, Sequence[str], None] = 'c57a61e06484'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely handle product column rename (may already be done on some DBs)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='products' AND column_name='update_at')
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='products' AND column_name='updated_at') THEN
                ALTER TABLE products RENAME COLUMN update_at TO updated_at;
            END IF;
        END $$;
    """)

    # Safely add discount columns if they don't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='discount_type') THEN
                ALTER TABLE orders ADD COLUMN discount_type varchar(20);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='discount_value') THEN
                ALTER TABLE orders ADD COLUMN discount_value numeric(10,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='discount_reason') THEN
                ALTER TABLE orders ADD COLUMN discount_reason varchar(255);
            END IF;
        END $$;
    """)

    # Convert orders.discount_type from varchar to discounttype ENUM if needed
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='orders' AND column_name='discount_type' AND data_type='character varying'
            ) THEN
                ALTER TABLE orders ALTER COLUMN discount_type TYPE discounttype USING discount_type::discounttype;
            END IF;
        END $$;
    """)

def downgrade() -> None:
    op.add_column('products', sa.Column('update_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True))
    op.execute('UPDATE products SET update_at = updated_at')
    op.alter_column('products', 'update_at', nullable=False)
    op.drop_column('products', 'updated_at')

    # Convert back to varchar
    op.execute("ALTER TABLE orders ALTER COLUMN discount_type TYPE varchar(20) USING discount_type::varchar")

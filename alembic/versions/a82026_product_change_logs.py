"""add product change audit logs

Revision ID: a82026productlogs
Revises: a82026paymentcash
Create Date: 2026-08-20
"""
from typing import Sequence, Union
from alembic import op

revision: str = "a82026productlogs"
down_revision: Union[str, None] = "a82026paymentcash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS product_change_logs (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            changed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            change_type VARCHAR(30) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_change_logs_product_id ON product_change_logs (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_change_logs_changed_by_user_id ON product_change_logs (changed_by_user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_change_logs_created_at ON product_change_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_change_logs")

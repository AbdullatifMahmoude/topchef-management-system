"""replace runtime daily sequences with an atomic counter table

Revision ID: a82526ordercounter
Revises: a82526waoutbox
"""
from alembic import op
import sqlalchemy as sa


revision = "a82526ordercounter"
down_revision = "a82526waoutbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_order_counters",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("terminal_id", sa.String(32), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("business_date", "terminal_id"),
    )
    # Preserve numbering when upgrading a database that already has orders.
    op.execute("""
        INSERT INTO daily_order_counters (business_date, terminal_id, last_value)
        SELECT order_date, split_part(order_number, '-', 1),
               MAX(split_part(order_number, '-', 2)::integer)
        FROM orders
        WHERE order_number ~ '^[^-]+-[0-9]+$'
        GROUP BY order_date, split_part(order_number, '-', 1)
    """)


def downgrade():
    op.drop_table("daily_order_counters")

"""Store immutable cashier request fingerprints for safe retries.

Revision ID: a103026cashattempt
Revises: a102626cashcustody
"""
from alembic import op
import sqlalchemy as sa

revision = "a103026cashattempt"
down_revision = "a102626cashcustody"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cashier_order_attempts",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("cashier_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="RESTRICT"), unique=True),
    )


def downgrade():
    op.drop_table("cashier_order_attempts")

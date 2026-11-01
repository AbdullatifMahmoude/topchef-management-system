"""add private customer account notifications

Revision ID: a92126custnotify
Revises: a92126customeremail
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a92126custnotify"
down_revision: Union[str, None] = "a92126customeremail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("customer_id", "event_key", name="uq_customer_notification_event"),
    )
    op.create_index("ix_customer_notifications_customer_id", "customer_notifications", ["customer_id"])
    op.create_index("ix_customer_notifications_order_id", "customer_notifications", ["order_id"])
    op.create_index("ix_customer_notifications_is_read", "customer_notifications", ["is_read"])
    op.create_index("ix_customer_notifications_created_at", "customer_notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("customer_notifications")

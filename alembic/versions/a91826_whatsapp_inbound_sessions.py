"""add inbound-only WhatsApp order sessions

Revision ID: a91826wainbound
Revises: a91626shiftcashadd
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a91826wainbound"
down_revision: Union[str, None] = "a91626shiftcashadd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_order_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_phone", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column("last_customer_message_at", sa.DateTime(), nullable=False),
        sa.Column("service_window_expires_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_whatsapp_subscription_order"),
    )
    op.create_index("ix_whatsapp_order_subscriptions_order_id", "whatsapp_order_subscriptions", ["order_id"])
    op.create_index("ix_whatsapp_order_subscriptions_customer_id", "whatsapp_order_subscriptions", ["customer_id"])
    op.create_index("ix_whatsapp_order_subscriptions_phone", "whatsapp_order_subscriptions", ["whatsapp_phone"])
    op.create_index("ix_whatsapp_order_subscriptions_status", "whatsapp_order_subscriptions", ["status"])
    op.create_index("ix_whatsapp_order_subscriptions_window", "whatsapp_order_subscriptions", ["service_window_expires_at"])

    op.create_table(
        "whatsapp_inbound_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meta_message_id", sa.String(255), nullable=False),
        sa.Column("whatsapp_phone", sa.String(20), nullable=False),
        sa.Column("message_type", sa.String(30), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("button_payload", sa.String(255), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("processing_result", sa.String(255), nullable=True),
    )
    op.create_index("ix_whatsapp_inbound_message_id", "whatsapp_inbound_messages", ["meta_message_id"], unique=True)
    op.create_index("ix_whatsapp_inbound_phone", "whatsapp_inbound_messages", ["whatsapp_phone"])

    op.create_table(
        "whatsapp_conversations",
        sa.Column("whatsapp_phone", sa.String(20), primary_key=True),
        sa.Column("state", sa.String(50), nullable=False, server_default="idle"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_whatsapp_conversations_expires_at", "whatsapp_conversations", ["expires_at"])

    op.add_column("whatsapp_outbox", sa.Column("message_type", sa.String(20), nullable=False, server_default="template"))
    op.add_column("whatsapp_outbox", sa.Column("interactive_payload", sa.Text(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("service_window_expires_at", sa.DateTime(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("subscription_id", sa.Integer(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("skip_reason", sa.String(255), nullable=True))
    op.create_foreign_key("fk_whatsapp_outbox_subscription", "whatsapp_outbox", "whatsapp_order_subscriptions", ["subscription_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_whatsapp_outbox_subscription_id", "whatsapp_outbox", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_outbox_subscription_id", table_name="whatsapp_outbox")
    op.drop_constraint("fk_whatsapp_outbox_subscription", "whatsapp_outbox", type_="foreignkey")
    for column in ("skip_reason", "subscription_id", "service_window_expires_at", "interactive_payload", "message_type"):
        op.drop_column("whatsapp_outbox", column)
    op.drop_index("ix_whatsapp_conversations_expires_at", table_name="whatsapp_conversations")
    op.drop_table("whatsapp_conversations")
    op.drop_index("ix_whatsapp_inbound_phone", table_name="whatsapp_inbound_messages")
    op.drop_index("ix_whatsapp_inbound_message_id", table_name="whatsapp_inbound_messages")
    op.drop_table("whatsapp_inbound_messages")
    op.drop_index("ix_whatsapp_order_subscriptions_window", table_name="whatsapp_order_subscriptions")
    op.drop_index("ix_whatsapp_order_subscriptions_status", table_name="whatsapp_order_subscriptions")
    op.drop_index("ix_whatsapp_order_subscriptions_phone", table_name="whatsapp_order_subscriptions")
    op.drop_index("ix_whatsapp_order_subscriptions_customer_id", table_name="whatsapp_order_subscriptions")
    op.drop_index("ix_whatsapp_order_subscriptions_order_id", table_name="whatsapp_order_subscriptions")
    op.drop_table("whatsapp_order_subscriptions")

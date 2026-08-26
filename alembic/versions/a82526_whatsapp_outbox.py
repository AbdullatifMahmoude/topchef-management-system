"""add durable WhatsApp transactional outbox

Revision ID: a82526waoutbox
Revises: a82526productuq
"""
from alembic import op
import sqlalchemy as sa


revision = "a82526waoutbox"
down_revision = "a82526productuq"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "whatsapp_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(64), nullable=False, unique=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("template_name", sa.String(512), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_whatsapp_outbox_event_key", "whatsapp_outbox", ["event_key"], unique=True)
    op.create_index("ix_whatsapp_outbox_order_id", "whatsapp_outbox", ["order_id"])
    op.create_index("ix_whatsapp_outbox_status", "whatsapp_outbox", ["status"])
    op.create_index("ix_whatsapp_outbox_next_attempt_at", "whatsapp_outbox", ["next_attempt_at"])


def downgrade():
    op.drop_table("whatsapp_outbox")

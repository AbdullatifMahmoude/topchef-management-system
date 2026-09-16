"""add WhatsApp consent and delivery tracking

Revision ID: a91426waconsent
Revises: a91226customeraccounts
"""
from alembic import op
import sqlalchemy as sa


revision = "a91426waconsent"
down_revision = "a91226customeraccounts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("whatsapp_status", sa.String(20), nullable=False, server_default="unknown"))
    op.add_column("customers", sa.Column("whatsapp_consent_at", sa.DateTime(), nullable=True))
    op.add_column("customers", sa.Column("whatsapp_checked_at", sa.DateTime(), nullable=True))
    op.add_column("customers", sa.Column("whatsapp_failure_reason", sa.String(255), nullable=True))
    op.add_column(
        "orders",
        sa.Column("whatsapp_initial_contact_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("whatsapp_outbox", sa.Column("meta_message_id", sa.String(255), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("template_parameters", sa.Text(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("button_payloads", sa.Text(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("delivery_status", sa.String(20), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("delivery_updated_at", sa.DateTime(), nullable=True))
    op.add_column("whatsapp_outbox", sa.Column("delivery_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_whatsapp_outbox_meta_message_id",
        "whatsapp_outbox",
        ["meta_message_id"],
        unique=True,
    )
    op.create_index("ix_whatsapp_outbox_customer_id", "whatsapp_outbox", ["customer_id"])


def downgrade():
    op.drop_index("ix_whatsapp_outbox_customer_id", table_name="whatsapp_outbox")
    op.drop_index("ix_whatsapp_outbox_meta_message_id", table_name="whatsapp_outbox")
    op.drop_column("whatsapp_outbox", "delivery_error")
    op.drop_column("whatsapp_outbox", "delivery_updated_at")
    op.drop_column("whatsapp_outbox", "delivery_status")
    op.drop_column("whatsapp_outbox", "meta_message_id")
    op.drop_column("whatsapp_outbox", "button_payloads")
    op.drop_column("whatsapp_outbox", "template_parameters")
    op.drop_column("whatsapp_outbox", "customer_id")
    op.drop_column("orders", "whatsapp_initial_contact_allowed")
    op.drop_column("customers", "whatsapp_failure_reason")
    op.drop_column("customers", "whatsapp_checked_at")
    op.drop_column("customers", "whatsapp_consent_at")
    op.drop_column("customers", "whatsapp_status")

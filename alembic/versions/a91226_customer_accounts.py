"""add customer accounts and trusted devices

Revision ID: a91226customeraccounts
Revises: a90326menunames
"""
from alembic import op
import sqlalchemy as sa

revision = "a91226customeraccounts"
down_revision = "a90326menunames"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("pin_hash", sa.String(255), nullable=True))
    op.add_column("customers", sa.Column("account_activated_at", sa.DateTime(), nullable=True))
    op.create_table(
        "customer_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(120), nullable=False, server_default="Device"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_devices_customer_id", "customer_devices", ["customer_id"])
    op.create_index("ix_customer_devices_refresh_token_hash", "customer_devices", ["refresh_token_hash"], unique=True)
    op.create_index("ix_customer_devices_expires_at", "customer_devices", ["expires_at"])


def downgrade():
    op.drop_table("customer_devices")
    op.drop_column("customers", "account_activated_at")
    op.drop_column("customers", "pin_hash")

"""add text values for WhatsApp settings

Revision ID: a82526whatsapp
Revises: a82226offerrules
"""
from alembic import op
import sqlalchemy as sa


revision = "a82526whatsapp"
down_revision = "a82226offerrules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_settings", sa.Column("value_text", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("app_settings", "value_text")

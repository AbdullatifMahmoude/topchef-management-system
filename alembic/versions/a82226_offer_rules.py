"""add advanced offer types and rules

Revision ID: a82226offerrules
Revises: a82226offerusage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a82226offerrules"
down_revision = "a82226offerusage"
branch_labels = None
depends_on = None


def upgrade():
    for value in (
        "COMBO", "BUY_X_GET_Y", "QUANTITY_DISCOUNT",
        "FREE_DELIVERY", "CATEGORY_DISCOUNT", "HAPPY_HOUR",
    ):
        op.execute(f"ALTER TYPE discount_type ADD VALUE IF NOT EXISTS '{value}'")
    op.add_column(
        "offers",
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    op.drop_column("offers", "rules")

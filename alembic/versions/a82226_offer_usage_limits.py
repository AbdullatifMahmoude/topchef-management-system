"""allow configured repeat offer usage per customer

Revision ID: a82226offerusage
Revises: a82226offerproducts
"""
from alembic import op
import sqlalchemy as sa


revision = "a82226offerusage"
down_revision = "a82226offerproducts"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_offer_customer_usage", "offer_usages", type_="unique")


def downgrade():
    op.create_unique_constraint(
        "uq_offer_customer_usage",
        "offer_usages",
        ["offer_id", "customer_phone"],
    )

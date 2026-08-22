"""allow offers to target selected products

Revision ID: a82226offerproducts
Revises: a82026expenses
Create Date: 2026-08-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a82226offerproducts"
down_revision: Union[str, None] = "a82026expenses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "offer_products",
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.offer_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("offer_id", "product_id"),
    )
    op.create_index("ix_offer_products_product_id", "offer_products", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_products_product_id", table_name="offer_products")
    op.drop_table("offer_products")

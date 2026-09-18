"""move legacy product uniqueness repair into migrations

Revision ID: a82526productuq
Revises: a82526resetcodes
"""
from alembic import op


revision = "a82526productuq"
down_revision = "a82526resetcodes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_product_name_key")
    op.execute("DROP INDEX IF EXISTS products_product_name_key")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS uq_product_name_cat_id")
    op.create_unique_constraint("uq_product_name_cat_id", "products", ["product_name", "cat_id"])


def downgrade():
    op.drop_constraint("uq_product_name_cat_id", "products", type_="unique")
    op.create_unique_constraint("products_product_name_key", "products", ["product_name"])

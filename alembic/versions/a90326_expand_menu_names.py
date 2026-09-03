"""expand menu name lengths to 255 characters

Revision ID: a90326menunames
Revises: a82526ordercounter
"""
from alembic import op
import sqlalchemy as sa


revision = "a90326menunames"
down_revision = "a82526ordercounter"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "categories", "cat_name", existing_type=sa.String(length=100),
        type_=sa.String(length=255), existing_nullable=False,
    )
    op.alter_column(
        "products", "product_name", existing_type=sa.String(length=100),
        type_=sa.String(length=255), existing_nullable=False,
    )
    op.alter_column(
        "variants", "name", existing_type=sa.String(length=50),
        type_=sa.String(length=255), existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "variants", "name", existing_type=sa.String(length=255),
        type_=sa.String(length=50), existing_nullable=False,
    )
    op.alter_column(
        "products", "product_name", existing_type=sa.String(length=255),
        type_=sa.String(length=100), existing_nullable=False,
    )
    op.alter_column(
        "categories", "cat_name", existing_type=sa.String(length=255),
        type_=sa.String(length=100), existing_nullable=False,
    )

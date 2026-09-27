"""Store the single loyalty reward chosen for an order.

Revision ID: a92626redeem
Revises: a92626points
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92626redeem"
down_revision: str | None = "a92626points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("loyalty_rule_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("loyalty_reward_type", sa.String(24), nullable=True))
        batch.add_column(sa.Column("loyalty_points_spent", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("loyalty_discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("loyalty_product_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("loyalty_product_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("loyalty_variant_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("loyalty_status", sa.String(12), nullable=True))
        batch.create_check_constraint("ck_orders_loyalty_points_nonnegative", "loyalty_points_spent >= 0")
        batch.create_check_constraint("ck_orders_loyalty_discount_nonnegative", "loyalty_discount_amount >= 0")
        batch.create_check_constraint("ck_orders_loyalty_status", "loyalty_status IS NULL OR loyalty_status IN ('reserved', 'consumed', 'reversed')")


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("ck_orders_loyalty_status", type_="check")
        batch.drop_constraint("ck_orders_loyalty_discount_nonnegative", type_="check")
        batch.drop_constraint("ck_orders_loyalty_points_nonnegative", type_="check")
        for name in ("loyalty_status", "loyalty_variant_name", "loyalty_product_name", "loyalty_product_id",
                     "loyalty_discount_amount", "loyalty_points_spent", "loyalty_reward_type", "loyalty_rule_id"):
            batch.drop_column(name)

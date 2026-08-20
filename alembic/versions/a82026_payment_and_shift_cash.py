"""add payment methods and shift cash reconciliation

Revision ID: a82026paymentcash
Revises: a82026reportidx
Create Date: 2026-08-20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a82026paymentcash"
down_revision: Union[str, None] = "a82026reportidx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    payment_method = postgresql.ENUM("CASH", "INSTAPAY", "WALLET", name="paymentmethod", create_type=False)
    payment_method.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method paymentmethod NOT NULL DEFAULT 'CASH'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_payment_method ON orders (payment_method)")
    op.execute("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS opening_cash NUMERIC(12, 2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS cash_expenses NUMERIC(12, 2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS actual_closing_cash NUMERIC(12, 2)")
    op.execute("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS closing_note TEXT")


def downgrade() -> None:
    op.drop_column("cashier_shifts", "closing_note")
    op.drop_column("cashier_shifts", "actual_closing_cash")
    op.drop_column("cashier_shifts", "cash_expenses")
    op.drop_column("cashier_shifts", "opening_cash")
    op.drop_index("idx_order_payment_method", table_name="orders")
    op.drop_column("orders", "payment_method")
    postgresql.ENUM(name="paymentmethod").drop(op.get_bind(), checkfirst=True)

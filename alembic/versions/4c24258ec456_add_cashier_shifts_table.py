"""add_cashier_shifts_table

Revision ID: 4c24258ec456
Revises: 8b44c8c5f40e
Create Date: 2026-07-12 04:12:00.694429

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4c24258ec456'
down_revision: Union[str, Sequence[str], None] = '8b44c8c5f40e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cashier_shifts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('target_date', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cashier_shifts_id'), 'cashier_shifts', ['id'], unique=False)
    op.create_index(op.f('ix_cashier_shifts_target_date'), 'cashier_shifts', ['target_date'], unique=False)
    op.create_index(op.f('ix_cashier_shifts_user_id'), 'cashier_shifts', ['user_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_cashier_shifts_user_id'), table_name='cashier_shifts')
    op.drop_index(op.f('ix_cashier_shifts_target_date'), table_name='cashier_shifts')
    op.drop_index(op.f('ix_cashier_shifts_id'), table_name='cashier_shifts')
    op.drop_table('cashier_shifts')

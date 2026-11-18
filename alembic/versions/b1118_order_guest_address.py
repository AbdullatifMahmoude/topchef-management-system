"""Preserve cashier order addresses without a customer phone."""
from alembic import op
import sqlalchemy as sa

revision = "b1118guestaddr"
down_revision = "a103026cashattempt"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("orders", sa.Column("guest_address", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("orders", "guest_address")

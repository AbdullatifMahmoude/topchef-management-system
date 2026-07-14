"""Track cashier-shift updates for incremental desktop synchronization."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8d3c1b9a7e21"
down_revision: Union[str, Sequence[str], None] = "4c24258ec456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cashier_shifts",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_column("cashier_shifts", "updated_at")

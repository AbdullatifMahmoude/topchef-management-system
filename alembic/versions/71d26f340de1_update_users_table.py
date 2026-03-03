"""update users table

Revision ID: 71d26f340de1
Revises: d6ffb3b5f5bf
Create Date: 2026-02-25 15:12:29.881726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71d26f340de1'
down_revision: Union[str, Sequence[str], None] = 'd6ffb3b5f5bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

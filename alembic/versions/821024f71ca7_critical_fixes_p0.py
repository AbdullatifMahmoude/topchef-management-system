"""critical_fixes_p0

Revision ID: 821024f71ca7
Revises: 71d26f340de1
Create Date: 2026-04-14 20:35:44.650112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '821024f71ca7'
down_revision: Union[str, Sequence[str], None] = '71d26f340de1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    pass

def downgrade():
    pass

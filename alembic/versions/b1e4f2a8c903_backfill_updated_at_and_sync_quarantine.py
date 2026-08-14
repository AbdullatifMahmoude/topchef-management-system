"""Backfill NULL updated_at values and add sync_quarantine table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.updated_at_backfill import backfill_null_updated_at_sync

revision: str = "b1e4f2a8c903"
down_revision: Union[str, Sequence[str], None] = "8d3c1b9a7e21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Ensure cashier_shifts.updated_at has server default (Postgres)
    if conn.dialect.name == "postgresql":
        op.alter_column(
            "cashier_shifts",
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )

    # Backfill any NULL updated_at across sync tables
    results = backfill_null_updated_at_sync(conn)
    if results:
        print(f"Backfilled updated_at: {results}")

    op.create_table(
        "sync_quarantine",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=100), nullable=False),
        sa.Column("record_key", sa.String(length=255), nullable=False),
        sa.Column("row_payload", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_failed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_failed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_quarantine_id", "sync_quarantine", ["id"], unique=False)
    op.create_index("ix_sync_quarantine_table_name", "sync_quarantine", ["table_name"], unique=False)
    op.create_index("ix_sync_quarantine_record_key", "sync_quarantine", ["record_key"], unique=False)
    op.create_index(
        "idx_sync_quarantine_lookup",
        "sync_quarantine",
        ["table_name", "record_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_sync_quarantine_lookup", table_name="sync_quarantine")
    op.drop_index("ix_sync_quarantine_record_key", table_name="sync_quarantine")
    op.drop_index("ix_sync_quarantine_table_name", table_name="sync_quarantine")
    op.drop_index("ix_sync_quarantine_id", table_name="sync_quarantine")
    op.drop_table("sync_quarantine")

"""Set the requested transfer number for InstaPay and wallet.

Revision ID: a92326transfer
Revises: a92126custnotify
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a92326transfer"
down_revision: str | None = "a92126custnotify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSFER_NUMBER = "01009515031"
KEYS = ("instapay_account", "wallet_number")


def upgrade() -> None:
    op.create_table(
        "transfer_number_previous_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
    )
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO transfer_number_previous_settings (key, value_text, is_deleted)
        SELECT key, value_text, is_deleted
        FROM app_settings
        WHERE key IN ('instapay_account', 'wallet_number')
    """))
    for key in KEYS:
        connection.execute(
            sa.text("""
                INSERT INTO app_settings (key, value_bool, value_text, description, is_deleted, updated_at)
                VALUES (:key, true, :number, 'Public transfer details', false, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE
                SET value_text = EXCLUDED.value_text,
                    is_deleted = false,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {"key": key, "number": TRANSFER_NUMBER},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for key in KEYS:
        connection.execute(
            sa.text("""
                DELETE FROM app_settings
                WHERE key = :key
                  AND value_text = :number
                  AND NOT EXISTS (
                      SELECT 1 FROM transfer_number_previous_settings WHERE key = :key
                  )
            """),
            {"key": key, "number": TRANSFER_NUMBER},
        )
    connection.execute(sa.text("""
        UPDATE app_settings AS current
        SET value_text = previous.value_text,
            is_deleted = previous.is_deleted,
            updated_at = CURRENT_TIMESTAMP
        FROM transfer_number_previous_settings AS previous
        WHERE current.key = previous.key
          AND current.value_text = :number
    """), {"number": TRANSFER_NUMBER})
    op.drop_table("transfer_number_previous_settings")

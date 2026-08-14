"""Backfill NULL updated_at values across sync-enabled tables."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import text

# Tables that participate in incremental desktop sync and have updated_at.
SYNC_TABLES_WITH_UPDATED_AT = [
    "users",
    "cashier_shifts",
    "categories",
    "products",
    "variants",
    "offers",
    "app_settings",
    "customers",
    "customer_addresses",
    "comments",
    "orders",
    "order_items",
    "order_status_history",
]


def _fallback_timestamp_sql(table: str) -> str:
    """Return SQL expression for fallback timestamp, preferring created_at / start_time."""
    if table == "cashier_shifts":
        return "COALESCE(start_time, CURRENT_TIMESTAMP)"
    if table in {"orders", "order_items", "order_status_history"}:
        return "COALESCE(created_at, changed_at, CURRENT_TIMESTAMP)"
    return "COALESCE(created_at, CURRENT_TIMESTAMP)"


async def backfill_null_updated_at(conn) -> dict[str, int]:
    """
    Backfill NULL updated_at in every sync table.
    Works with both SQLite (desktop) and Postgres (cloud).
    Returns {table_name: rows_updated}.
    """
    results: dict[str, int] = {}

    # Detect dialect
    dialect = conn.dialect.name if hasattr(conn, "dialect") else "sqlite"

    for table in SYNC_TABLES_WITH_UPDATED_AT:
        has_updated_at = False
        try:
            if dialect == "sqlite":
                check = await conn.execute(text(f"PRAGMA table_info({table})"))
                has_updated_at = any(row[1] == "updated_at" for row in check.all())
            else:
                pg_check = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = :table AND column_name = 'updated_at'"
                    ),
                    {"table": table},
                )
                has_updated_at = pg_check.first() is not None
        except Exception:
            continue

        if not has_updated_at:
            continue

        fallback = _fallback_timestamp_sql(table)
        stmt = text(f"UPDATE {table} SET updated_at = {fallback} WHERE updated_at IS NULL")
        try:
            result = await conn.execute(stmt)
            count = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
            if count:
                results[table] = count
        except Exception:
            continue
    return results


def backfill_null_updated_at_sync(connection) -> dict[str, int]:
    """Synchronous variant for Alembic migrations and standalone scripts."""
    results: dict[str, int] = {}
    dialect = connection.dialect.name
    for table in SYNC_TABLES_WITH_UPDATED_AT:
        if dialect == "sqlite":
            cols = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not any(c[1] == "updated_at" for c in cols):
                continue
        else:
            exists = connection.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = 'updated_at'"
                ),
                {"table": table},
            ).first()
            if not exists:
                continue

        fallback = _fallback_timestamp_sql(table)
        result = connection.execute(
            text(f"UPDATE {table} SET updated_at = {fallback} WHERE updated_at IS NULL")
        )
        if result.rowcount:
            results[table] = result.rowcount
    return results

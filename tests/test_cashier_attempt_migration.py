from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_cashier_attempt_migration_upgrades_and_downgrades_isolated_database(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/a103026_cashier_attempts.py"
    spec = spec_from_file_location("cashier_attempt_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        table = inspect(conn).get_columns("cashier_order_attempts")
        assert {column["name"] for column in table} == {"key", "cashier_id", "request_hash", "order_id"}
        migration.downgrade()
        assert not inspect(conn).has_table("cashier_order_attempts")
    engine.dispose()

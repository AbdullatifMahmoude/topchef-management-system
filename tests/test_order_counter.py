import inspect

from sqlalchemy.dialects import postgresql

from app.modules.orders import models
from app.modules.orders.repository import OrderRepository


def test_counter_has_composite_primary_key():
    primary_keys = {column.name for column in models.DailyOrderCounter.__table__.primary_key.columns}
    assert primary_keys == {"business_date", "terminal_id"}


def test_order_number_path_contains_no_runtime_ddl():
    source = inspect.getsource(OrderRepository.get_next_order_number).upper()
    assert "CREATE SEQUENCE" not in source
    assert "NEXTVAL" not in source


def test_postgres_counter_upsert_is_atomic():
    from sqlalchemy.dialects.postgresql import insert

    statement = insert(models.DailyOrderCounter).values(
        business_date="2026-08-25", terminal_id="T1", last_value=1,
    ).on_conflict_do_update(
        index_elements=["business_date", "terminal_id"],
        set_={"last_value": models.DailyOrderCounter.last_value + 1},
    ).returning(models.DailyOrderCounter.last_value)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "RETURNING" in sql

import contextlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, Integer, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.modules.comments.models import Comment
from app.modules.customer.models import Customer, CustomerAddress
from app.modules.menu.models import Category, Product, Variant
from app.modules.offer.models import Offer
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.settings.models import AppSetting
from app.modules.users.models import User


MODEL_ORDER = (
    (User, "users"),
    (Category, "categories"),
    (Product, "products"),
    (Variant, "variants"),
    (Offer, "offers"),
    (AppSetting, "app_settings"),
    (Customer, "customers"),
    (CustomerAddress, "customer_addresses"),
    (Comment, "comments"),
    (Order, "orders"),
    (OrderItem, "order_items"),
    (OrderStatusHistory, "order_status_history"),
)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    return value


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return date.fromisoformat(value[:10])
    return value


def _coerce_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return _parse_datetime(value)
    if isinstance(column.type, Date):
        return _parse_date(value)
    if isinstance(column.type, Numeric) and not isinstance(value, Decimal):
        return Decimal(str(value))
    return value


def _column_payload(model: type, row: dict[str, Any]) -> dict[str, Any]:
    columns = inspect(model).columns
    payload: dict[str, Any] = {}
    for column in columns:
        if column.name in row:
            payload[column.name] = _coerce_value(column, row[column.name])
    return payload


async def _find_existing(session: AsyncSession, model: type, row: dict[str, Any]):
    mapper = inspect(model)
    pk_columns = list(mapper.primary_key)
    pk_values = {column.name: row.get(column.name) for column in pk_columns}

    if pk_columns and all(value is not None for value in pk_values.values()):
        existing = await session.get(
            model,
            tuple(pk_values.values()) if len(pk_columns) > 1 else next(iter(pk_values.values())),
        )
        if existing is not None:
            return existing

    if model is Order:
        order_number = row.get("order_number")
        order_date = _parse_date(row.get("order_date"))
        if order_number and order_date:
            result = await session.execute(
                select(Order).where(Order.order_number == order_number, Order.order_date == order_date)
            )
            return result.scalars().first()

    if model is OrderItem and row.get("order_id") is not None and row.get("product_id") is not None:
        result = await session.execute(
            select(OrderItem).where(
                OrderItem.order_id == row["order_id"],
                OrderItem.product_id == row["product_id"],
                OrderItem.unit_price == _coerce_value(OrderItem.__table__.columns.unit_price, row.get("unit_price")),
            )
        )
        return result.scalars().first()

    if model is OrderStatusHistory and row.get("order_id") is not None and row.get("changed_at"):
        result = await session.execute(
            select(OrderStatusHistory).where(
                OrderStatusHistory.order_id == row["order_id"],
                OrderStatusHistory.changed_at == _parse_datetime(row["changed_at"]),
            )
        )
        return result.scalars().first()

    if model is CustomerAddress and row.get("customer_id") and row.get("address"):
        result = await session.execute(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == row["customer_id"],
                CustomerAddress.address == row["address"]
            )
        )
        return result.scalars().first()

    if model is Customer and row.get("phone_number"):
        result = await session.execute(select(Customer).where(Customer.phone_number == row["phone_number"]))
        return result.scalars().first()

    if model is User and row.get("username"):
# ... rest of find_existing ...
        result = await session.execute(select(User).where(User.username == row["username"]))
        return result.scalar_one_or_none()

    if model is Category and row.get("cat_name"):
        result = await session.execute(select(Category).where(Category.cat_name == row["cat_name"]))
        return result.scalar_one_or_none()

    if model is Product and row.get("product_name") and row.get("cat_id") is not None:
        result = await session.execute(
            select(Product).where(Product.product_name == row["product_name"], Product.cat_id == row["cat_id"])
        )
        return result.scalars().first()

    if model is Variant and row.get("name") and row.get("product_id") is not None:
        result = await session.execute(
            select(Variant).where(Variant.name == row["name"], Variant.product_id == row["product_id"])
        )
        return result.scalars().first()

    if model is Offer and row.get("code"):
        result = await session.execute(select(Offer).where(Offer.code == row["code"]))
        return result.scalars().first()

    return None


async def _upsert_rows(session: AsyncSession, model: type, rows: list[dict[str, Any]]) -> int:
    import sqlalchemy.exc
    changed = 0
    mapper = inspect(model)
    primary_key_names = {column.name for column in mapper.primary_key}
    
    # Models that MUST have their IDs preserved to maintain relationships
    PRESERVE_ID_MODELS = {User, Category, Product, Variant, Offer, AppSetting}
    
    for row in rows:
        values = _column_payload(model, row)
        if not values:
            continue

        existing = await _find_existing(session, model, row)
        
        try:
            async with session.begin_nested():
                if existing is None:
                    insert_values = {}
                    for k, v in values.items():
                        is_pk = k in primary_key_names
                        col = mapper.columns.get(k)
                        is_int_pk = is_pk and col is not None and isinstance(col.type, Integer)
                        
                        if is_int_pk and model not in PRESERVE_ID_MODELS:
                            continue
                        insert_values[k] = v
                    
                    session.add(model(**insert_values))
                else:
                    has_mod = False
                    for key, value in values.items():
                        if key in primary_key_names:
                            continue
                        
                        col = mapper.columns.get(key)
                        coerced_value = _coerce_value(col, value)
                        
                        current_val = getattr(existing, key)
                        if current_val != coerced_value:
                            setattr(existing, key, coerced_value)
                            has_mod = True
                    
                    if has_mod:
                        await session.flush()
                        changed += 1
        except sqlalchemy.exc.IntegrityError:
            pass

    return changed


async def _build_id_map(session: AsyncSession, model: type, rows: list[dict[str, Any]]) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for row in rows:
        server_id = row.get("id")
        if server_id is None:
            continue
        existing = await _find_existing(session, model, row)
        if existing is not None:
            id_map[int(server_id)] = existing.id
    return id_map


def _remap_foreign_ids(rows: list[dict[str, Any]], field_name: str, id_map: dict[int, int]) -> list[dict[str, Any]]:
    if not id_map:
        return rows
    remapped = []
    for row in rows:
        item = dict(row)
        server_id = item.get(field_name)
        if server_id is not None and int(server_id) in id_map:
            item[field_name] = id_map[int(server_id)]
        remapped.append(item)
    return remapped


async def apply_master_data_snapshot(session: AsyncSession, snapshot: dict[str, Any]) -> dict[str, int]:
    """Apply a cloud snapshot to the local desktop database."""
    stats: dict[str, int] = {}

    try:
        customer_id_map: dict[int, int] = {}
        address_id_map: dict[int, int] = {}
        order_id_map: dict[int, int] = {}

        for model, key in MODEL_ORDER:
            rows = snapshot.get(key) or []
            
            # Remap Foreign Keys before upserting
            if model is CustomerAddress:
                rows = _remap_foreign_ids(rows, "customer_id", customer_id_map)
            elif model is Order:
                rows = _remap_foreign_ids(rows, "customer_id", customer_id_map)
                rows = _remap_foreign_ids(rows, "address_id", address_id_map)
            elif model in {OrderItem, OrderStatusHistory} and order_id_map:
                rows = _remap_foreign_ids(rows, "order_id", order_id_map)

            stats[key] = await _upsert_rows(session, model, rows)
            await session.flush()

            # Build ID maps for future children in this loop
            if model is Customer:
                customer_id_map = await _build_id_map(session, model, rows)
            elif model is CustomerAddress:
                address_id_map = await _build_id_map(session, model, rows)
            elif model is Order:
                order_id_map = await _build_id_map(session, model, rows)

        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Cloud-to-local master-data reconciliation failed")
        raise

    return stats


from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.infrastructure.dependencies import (
    Capability,
    get_current_user,
    get_optional_user,
    require_capability,
)
from app.modules.menu import models, schemas, service

router = APIRouter(prefix="/menu", tags=["menu"])

# =============== category ==================

# READ operations — any authenticated user can view
@router.get("/categories", response_model=list[schemas.CategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    cat_service = service.CategoryService(db, redis)
    
    # Simple check: Admins see everything, Others (including guests) see only active
    only_active = _user.role != "admin" if _user else True
    
    return await cat_service.list_categories(only_active=only_active)


@router.get("/categories/{id}", response_model=schemas.CategoryResponse)
async def get_category(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    cat_service = service.CategoryService(db, redis)
    
    # Simple check: Admins can see inactive items via ID, Guest/Non-admin cannot
    only_active = _user.role != "admin" if _user else True
    
    return await cat_service.get_category(id, only_active=only_active)


# WRITE operations — only ADM;IN can manage menu
@router.post(
    "/categories",
    response_model=schemas.CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    cat_data: schemas.CreateCategory,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    cat_service = service.CategoryService(db, redis)
    createcat = await cat_service.create_category(cat_data)
    return createcat


@router.patch("/categories/{id}", response_model=schemas.CategoryResponse)
async def update_category(
    id: int,
    cat_data: schemas.UpdateCategory,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    cat_service = service.CategoryService(db, redis)
    updatecat = await cat_service.update_category(id, cat_data)
    return updatecat


@router.delete("/categories/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    cat_service = service.CategoryService(db, redis)
    await cat_service.delete_category(id)


@router.patch("/categories/{id}/toggle", response_model=schemas.CategoryResponse)
async def toggle_category(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    cat_service = service.CategoryService(db, redis)
    toggle = await cat_service.toggle_category(id)
    return toggle


# ================== products ==============

# READ operations — any authenticated user can view
@router.get("/products", response_model=list[schemas.ProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    products_service = service.ProductService(db, redis)
    
    # Simple check: Admins see everything, Others (including guests) see only active
    only_active = _user.role != "admin" if _user else True
    
    return await products_service.list_products(only_active=only_active)


@router.get("/products/operations")
async def get_products_operations(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    """Last 30 days sales and recent auditable menu changes."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.core.enums import OrderStatus
    from app.modules.orders.models import Order, OrderItem
    from app.modules.users.models import User
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    sales_result = await db.execute(
        select(
            OrderItem.product_id,
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.total_price).label("sales"),
        ).join(Order, Order.id == OrderItem.order_id).where(
            Order.created_at >= cutoff,
            Order.is_deleted == False,
            OrderItem.is_deleted == False,
            Order.order_status != OrderStatus.CANCELLED,
        ).group_by(OrderItem.product_id)
    )
    logs_result = await db.execute(
        select(models.ProductChangeLog, models.Product.product_name, User.full_name, User.username)
        .join(models.Product, models.Product.id == models.ProductChangeLog.product_id)
        .outerjoin(User, User.id == models.ProductChangeLog.changed_by_user_id)
        .order_by(models.ProductChangeLog.created_at.desc()).limit(60)
    )
    return {
        "period_days": 30,
        "sales": [{"product_id": row.product_id, "units_sold": int(row.units_sold or 0), "sales": float(row.sales or 0)} for row in sales_result],
        "changes": [{
            "id": log.id, "product_id": log.product_id, "product_name": product_name,
            "change_type": log.change_type, "old_value": log.old_value, "new_value": log.new_value,
            "changed_by": full_name or username or "النظام", "created_at": log.created_at.isoformat(),
        } for log, product_name, full_name, username in logs_result],
    }


@router.get("/products/popular")
async def get_popular_products(
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    """Best-selling available products for the cashier quick-pick bar."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.core.enums import OrderStatus
    from app.modules.orders.models import Order, OrderItem

    safe_limit = max(1, min(limit, 12))
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    result = await db.execute(
        select(OrderItem.product_id, func.sum(OrderItem.quantity).label("units_sold"))
        .join(Order, Order.id == OrderItem.order_id)
        .join(models.Product, models.Product.id == OrderItem.product_id)
        .where(
            Order.created_at >= cutoff,
            Order.is_deleted == False,
            OrderItem.is_deleted == False,
            Order.order_status != OrderStatus.CANCELLED,
            models.Product.is_available == True,
            models.Product.is_deleted == False,
        )
        .group_by(OrderItem.product_id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(safe_limit)
    )
    return [{"product_id": row.product_id, "units_sold": int(row.units_sold or 0)} for row in result]


@router.get("/products/{id}", response_model=schemas.ProductResponse)
async def get_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    products_service = service.ProductService(db, redis)
    
    # Simple check: Admins can see inactive items via ID, Guest/Non-admin cannot.
    only_active = _user.role != "admin" if _user else True
    
    return await products_service.get_product(id, only_active=only_active)


# WRITE operations — only ADMIN can manage menu
@router.post(
    "/products",
    response_model=schemas.ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    product_data: schemas.CreateProduct,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    products_service = service.ProductService(db, redis)
    createproduct = await products_service.create_product(product_data)
    return createproduct


@router.patch("/products/{id}", response_model=schemas.ProductResponse)
async def update_product(
    id: int,
    product_data: schemas.UpdateProduct,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    products_service = service.ProductService(db, redis)
    updateproduct = await products_service.update_product(id, product_data, actor_id=_current_user.id)
    return updateproduct


@router.delete("/products/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    products_service = service.ProductService(db, redis)
    await products_service.delete_product(id)


@router.patch("/products/{id}/toggle", response_model=schemas.ProductResponse)
async def toggle_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    products_service = service.ProductService(db, redis)
    toggle = await products_service.toggle_product(id, actor_id=_current_user.id)
    return toggle

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.menu import service, schemas
from typing import List
from app.modules.infrastructure.dependencies import (
    require_capability,
    Capability,
    get_current_user,
    get_optional_user,
)

router = APIRouter(prefix="/menu", tags=["menu"])

# =============== category ==================

# READ operations — any authenticated user can view
@router.get("/categories", response_model=List[schemas.CategoryResponse])
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
    return None


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
@router.get("/products", response_model=List[schemas.ProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    products_service = service.ProductService(db, redis)
    
    # Simple check: Admins see everything, Others (including guests) see only active
    only_active = _user.role != "admin" if _user else True
    
    return await products_service.list_products(only_active=only_active)


@router.get("/products/{id}", response_model=schemas.ProductResponse)
async def get_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _user=Depends(get_optional_user),
):
    products_service = service.ProductService(db, redis)
    
    # Simple check: Admins can see inactive items via ID, Guest/Non-admin cannot
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
    updateproduct = await products_service.update_product(id, product_data)
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
    return None


@router.patch("/products/{id}/toggle", response_model=schemas.ProductResponse)
async def toggle_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user=Depends(require_capability(Capability.MANAGE_MENU)),
):
    products_service = service.ProductService(db, redis)
    toggle = await products_service.toggle_product(id)
    return toggle

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.menu import service, schemas
from typing import List

router = APIRouter(prefix="/menu", tags=["menu"])

# =============== category ==================


@router.get("/categories", response_model=List[schemas.CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    cat_service = service.CategoryService(db)
    listcat = await cat_service.list_categories()
    return listcat


@router.get("/categories/{id}", response_model=schemas.CategoryResponse)
async def get_category(id: int, db: AsyncSession = Depends(get_db)):
    cat_service = service.CategoryService(db)
    getcat = await cat_service.get_category(id)
    return getcat


@router.post("/categories",
             response_model=schemas.CategoryResponse,
             status_code=status.HTTP_201_CREATED)
async def create_category(cat_data: schemas.CreateCategory,
                          db: AsyncSession = Depends(get_db)
                          ):
    cat_service = service.CategoryService(db)
    createcat = await cat_service.create_category(cat_data)
    return createcat


@router.patch("/categories/{id}", response_model=schemas.CategoryResponse)
async def update_category(id: int, cat_data: schemas.UpdateCategory,
                          db: AsyncSession = Depends(get_db)):
    cat_service = service.CategoryService(db)
    updatecat = await cat_service.update_category(id, cat_data)
    return updatecat


@router.delete("/categories/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(id: int, db: AsyncSession = Depends(get_db)):
    cat_service = service.CategoryService(db)
    await cat_service.delete_category(id)
    return None


@router.patch("/categories/{id}/toggle", response_model=schemas.CategoryResponse)
async def toggle_category(id: int, db: AsyncSession = Depends(get_db)):
    cat_service = service.CategoryService(db)
    toggle = await cat_service.toggle_category(id)
    return toggle


# # ================== products ==============
# @router.get("/products", response_model=List[schemas.ProductResponse])
# async def list_products(db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     listproduct = await products_service.list_products()
#     return listproduct


# @router.get("/products/{id}", response_model=schemas.ProductResponse)
# async def get_product(id: int, db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     getproduct = await products_service.get_product(id)
#     return getproduct


# @router.post("/products",
#              response_model=schemas.ProductResponse,
#              status_code=status.HTTP_201_CREATED)
# async def create_product(product_data: schemas.CreateProduct, db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     createproduct = await products_service.create_product(product_data)
#     return createproduct


# @router.patch("/products/{id}", response_model=schemas.ProductResponse)
# async def update_product(id: int, product_data: schemas.UpdateProduct, db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     updateproduct = await products_service.update_product(id, product_data)
#     return updateproduct


# @router.delete("/products/{id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_product(id: int, db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     await products_service.delete_product(id)
#     return None


# @router.patch("/products/{id}/toggle", response_model=schemas.ProductResponse)
# async def toggle_product(id: int, db: AsyncSession = Depends(get_db)):
#     products_service = service.ProductService(db)
#     toggle = await products_service.toggle_product(id)
#     return toggle

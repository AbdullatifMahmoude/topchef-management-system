from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.modules.menu import models, schemas
from typing import Optional
from sqlalchemy import delete
from sqlalchemy.orm import selectinload


# ============== category ===============#
class CategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_name(self, catname: str):
        cat = await self.db.execute(select(models.Category).where(
            models.Category.cat_name == catname,
            models.Category.is_deleted == False
        ))
        return cat.scalars().first()

    async def get_by_id(self, catid: int):
        cat = await self.db.execute(select(models.Category).where(
            models.Category.id == catid,
            models.Category.is_deleted == False
        ))
        return cat.scalars().first()

    async def list_category(self, only_active: bool = False):
        query = select(models.Category).where(models.Category.is_deleted == False)
        if only_active:
            query = query.where(models.Category.is_active == True)
        
        listcat = await self.db.execute(query.order_by(models.Category.id))
        return listcat.scalars().all()

    async def create_category(self, catdata: schemas.CreateCategory):
        new_category = models.Category(**catdata.model_dump())
        self.db.add(new_category)
        return new_category

    async def update_category(self, category: models.Category, catdata: schemas.UpdateCategory):
        update_category = catdata.model_dump(exclude_unset=True)

        for key, value in update_category.items():
            setattr(category, key, value)

        return category

    async def delete_category(self, category: models.Category):
        import time
        ts = int(time.time())
        category.is_deleted = True
        category.cat_name = f"{category.cat_name}_deleted_{ts}"
        
        # Also soft delete all products in this category
        for product in category.products:
            product.is_deleted = True
            product.product_name = f"{product.product_name}_deleted_{ts}"
            # Also soft delete variants for each product
            for variant in product.variants:
                variant.is_deleted = True

    async def toggle_active(self, category: models.Category):
        category.toggle_active()
        return category


# ============== product ===============#
class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, productid: int):
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(models.Product.id == productid, models.Product.is_deleted == False)
        product = await self.db.execute(stmt)
        return product.scalar_one_or_none()

    async def get_by_name(self, productname: str, cat_id: int) -> models.Product:
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(
            models.Product.product_name == productname,
            models.Product.cat_id == cat_id,
            models.Product.is_deleted == False
        )
        product = await self.db.execute(stmt)
        return product.scalars().first()

    async def get_by_ids(self, product_ids: list[int]):
        """Get multiple products by IDs."""
        if not product_ids:
            return []
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(
            models.Product.id.in_(product_ids),
            models.Product.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_products(self, only_active: bool = False):
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(models.Product.is_deleted == False)
        
        if only_active:
            stmt = stmt.join(models.Category).where(
                models.Product.is_available == True,
                models.Category.is_active == True
            )
            
        stmt = stmt.order_by(models.Product.is_available.desc(), models.Product.id)
        listproduct = await self.db.execute(stmt)
        return listproduct.scalars().all()

    async def create_product(self, product: models.Product):
        self.db.add(product)
        return product

    async def update_product(self, product: models.Product, productdata: schemas.UpdateProduct):
        update_data = productdata.model_dump(exclude_unset=True, exclude={"variants"})
        for key, value in update_data.items():
            setattr(product, key, value)

        return product

    async def delete_product(self, product: models.Product):
        import time
        ts = int(time.time())
        product.is_deleted = True
        product.product_name = f"{product.product_name}_deleted_{ts}"
        # Also soft delete variants
        for variant in product.variants:
            variant.is_deleted = True

    async def toggle_active(self, product: models.Product):
        product.toggle_availability()
        return product


# ============== variant ===============#
class VariantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_product_id(self, productid: int):
        result = await self.db.execute(
            select(models.Variant).where(
                models.Variant.product_id == productid,
                models.Variant.is_deleted == False
            ).order_by(models.Variant.id)
        )
        return result.scalars().all()

    async def create_variant(self, variant: list[models.Variant]):
        self.db.add_all(variant)
        return variant

    async def delete_by_product_id(self, product_id: int):
        from sqlalchemy import update
        stmt = update(models.Variant).where(
            models.Variant.product_id == product_id
        ).values(is_deleted=True)
        await self.db.execute(stmt)

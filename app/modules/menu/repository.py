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
        cat = await self.db.execute(select(models.Category).where(models.Category.cat_name == catname))
        return cat.scalars().first()

    async def get_by_id(self, catid: int):
        cat = await self.db.execute(select(models.Category).where(models.Category.id == catid))
        return cat.scalars().first()

    async def list_category(self):
        listcat = await self.db.execute(select(models.Category).order_by(models.Category.id))
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
        await self.db.delete(category)

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
        ).where(models.Product.id == productid)
        product = await self.db.execute(stmt)
        return product.scalar_one_or_none()

    async def get_by_name(self, productname: str) -> models.Product:
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(models.Product.product_name == productname)
        product = await self.db.execute(stmt)
        return product.scalars().first()

    async def get_by_ids(self, product_ids: list[int]):
        """Get multiple products by IDs."""
        if not product_ids:
            return []
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).where(models.Product.id.in_(product_ids))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_products(self):
        stmt = select(models.Product).options(
            selectinload(models.Product.category),
            selectinload(models.Product.variants)
        ).order_by(models.Product.is_available.desc(), models.Product.id)
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
        await self.db.delete(product)

    async def toggle_active(self, product: models.Product):
        product.toggle_availability()
        return product


# ============== variant ===============#
class VariantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_product_id(self, productid: int):
        result = await self.db.execute(select(models.Variant).where(models.Variant.product_id == productid).order_by(models.Variant.id))
        return result.scalars().all()

    async def create_variant(self, variant: list[models.Variant]):
        self.db.add_all(variant)
        return variant

    async def delete_by_product_id(self, product_id: int):
        stmt = delete(models.Variant).where(
            models.Variant.product_id == product_id
        )
        await self.db.execute(stmt)


# # ============== addons ===============#
# class AddonsRepository:
#     def __init__(self, db: AsyncSession):
#         self.db = db

#     async def get_by_addon_id(self, addonsid: int):
#         addon = await self.db.execute(select(models.Addon).where(models.Addon.id == addonsid))
#         return addon.scalars().first()

#     async def create_addon(self, addondata: schemas.CreateAddon):
#         addon = models.Addon(**addondata.model_dump())
#         self.db.add(addon)
#         return addon

#     async def update_addon(self, addon: models.Addon, addondata: schemas.UpdateAddon):
#         update_addon = addondata.model_dump(exclude_unset=True)
#         for key, value in update_addon.items():
#             setattr(addon, key, value)

#         return addon

#     async def delete_addon(self, addon: models.Addon):
#         await self.db.delete(addon)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.modules.menu import models, schemas
from typing import Optional


class CategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_name(self, catname: str):
        cat = await self.db.execute(select(models.Category).filter(models.Category.cat_name == catname))
        return cat.scalars().first()

    async def get_by_id(self, catid: int):
        cat = await self.db.execute(select(models.Category).filter(models.Category.id == catid))
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
        category.is_active = not category.is_active
        return category


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, productid: int):
        product =  await self.db.execute(select(models.Product).filter(models.Product.id == productid))
        return product.scalars().first()

    async def get_by_name(self, productname: str) -> models.Product:
        product = await self.db.execute(select(models.Product).filter(models.Product.product_name == productname))
        return product.scalars().first()

    async def list_products(self):
        listproduct = await self.db.execute(select(models.Product).order_by(models.Product.is_available.desc(), models.Product.id))
        return listproduct.scalars().all()

    async def create_product(self, productdata: schemas.CreateProduct):
        new_product = models.Product(**productdata.model_dump())
        self.db.add(new_product)
        return new_product

    async def update_product(self, product: models.Product, productdata: schemas.UpdateProduct):
        update_data = productdata.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(product, key, value)
        
        return product
        

    async def delete_product(self, product: models.Product):
        await self.db.delete(product)


    async def toggle_active(self, product: models.Product):
        product.is_available = not product.is_available
        return product
       

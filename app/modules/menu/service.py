from app.modules.menu import repository, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ValidationError, NotFoundError
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select


# ============== category ===============#
class CategoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = repository.CategoryRepository(db)

    async def get_category(self, category_id: int):
        category = await self.repo.get_by_id(category_id)

        if not category:
            raise NotFoundError(f"Category with id:{category_id}")

        return category

    async def get_category_by_name(self, cat_name: str):
        cat = await self.repo.get_by_name(cat_name)
        return cat

    async def list_categories(self):
        listcat = await self.repo.list_category()
        return [schemas.CategoryResponse.from_orm(c) for c in listcat]

    async def create_category(self, category_data: schemas.CreateCategory):
        async with self.db.begin():
            existing = await self.repo.get_by_name(category_data.cat_name)

            if existing:
                raise ValidationError(
                    f"Category '{category_data.cat_name}' already exists")

            createcat = await self.repo.create_category(category_data)

        return schemas.CategoryResponse.from_orm(createcat)

    async def update_category(self, cat_id: int, cat_data: schemas.UpdateCategory):
        async with self.db.begin():
            existing = await self.get_category(cat_id)

            if cat_data.cat_name is not None:
                exist_name = await self.repo.get_by_name(cat_data.cat_name)
                if exist_name and exist_name.id != cat_id:
                    raise ValidationError(
                        f"Category '{cat_data.cat_name}' already exists")

            updatecat = await self.repo.update_category(existing, cat_data)

        return schemas.CategoryResponse.from_orm(updatecat)

    async def delete_category(self, category_id: int):
        async with self.db.begin():
            category = await self.get_category(category_id)

            await self.repo.delete_category(category)
        return True

    async def toggle_category(self, category_id: int):
        async with self.db.begin():
            category = await self.get_category(category_id)
            toggle = await self.repo.toggle_active(category)

        return schemas.CategoryResponse.from_orm(toggle)


# # ============== product ===============#
# class ProductService:
#     def __init__(self, db: AsyncSession):
#         self.db = db
#         self.repo = repository.ProductRepository(db)
#         self.category_service = CategoryService(db)

#     async def get_product(self, product_id: int):
#         product = await self.repo.get_by_id(product_id)
#         if not product:
#             raise NotFoundError(f"Product With id:{product_id}")

#         return product

#     async def get_product_by_name(self, product_name: str):
#         product = await self.repo.get_by_name(product_name)
#         return product

#     async def list_products(self):
#         listproduct = await self.repo.list_products()
#         return [schemas.ProductResponse.from_orm(c) for c in listproduct]

#     async def create_product(self, product_data: schemas.CreateProduct):
#         async with self.db.begin():
#             product = await self.repo.get_by_name(product_data.name)
#             if product:
#                 raise ValidationError(
#                     f"Product with name: {product_data.name} already exist")

#             createproduct = await self.repo.create_product(product_data)
#             await self.db.flush()
#             stmt = select(models.Product).options(selectinload(
#                 models.Product.category)).where(models.Product.cat_id == product_data.cat_id)
#             result = await self.db.execute(stmt)
#             product_with_cat = result.scalar_one()
#         return schemas.ProductResponse.from_orm(product_with_cat)

#     async def update_product(self, product_id: int, product_data: schemas.UpdateProduct):
#         async with self.db.begin():
#             existing = await self.get_product(product_id)

#             if product_data.cat_id is not None:
#                 await self.category_service.get_category(product_data.cat_id)

#             if product_data.name:
#                 exist_name = await self.repo.get_by_name(product_data.name)
#                 if exist_name and exist_name.id != product_id:
#                     raise ValidationError(
#                         f"Product with name: {product_data.name} already exist")

#             updateproduct = await self.repo.update_product(existing, product_data)
#             await self.db.flush
#             stmt = select(models.Product).options(selectinload(models.Product.category)).where(models.Product.cat_id == product_data.cat_id)
#             result = await self.db.execute(stmt)
#             product_with_cat = result.scalar_one()
#         return schemas.ProductResponse.from_orm(product_with_cat)

#     async def delete_product(self, product_id: int):
#         async with self.db.begin():
#             product = await self.get_product(product_id)
#             await self.repo.delete_product(product)
#         return True

#     async def toggle_product(self, product_id: int):
#         async with self.db.begin():
#             product = await self.get_product(product_id)
#             toggle = await self.repo.toggle_active(product)
#             await self.db.flush
#             stmt = select(models.Product).options(selectinload(models.Product.category)).where(models.Product.cat_id == product_data.cat_id)
#             result = await self.db.execute(stmt)
#             product_with_cat = result.scalar_one()
#         return schemas.ProductResponse.from_orm(product_with_cat)


# # ============== variant ===============#
# class VariantService:
#     def __init__(self, db: AsyncSession):
#         self.db = db
#         self.repo = repository.VariantRepository(db)
#         self.product_service = ProductService(db)

#     async def get_by_product_id(self, product_id: int):
#         await self.product_service.get_product(product_id)
#         variants = await self.repo.get_by_product_id(product_id)
#         return variants

#     async def create_variant(self, variantdata: schemas.CreateVariant):
#         async with self.db.begin():
#             await self.product_service.get_product(variantdata.product_id)
#             variant = self.repo.create_variant(variantdata)
#             stmt = select(models.Variant).options(selectinload(models.Variant.product)).where(models.Variant.product_id == variantdata.product_id)
#             result = await self.db.execute()
#             variant  

        

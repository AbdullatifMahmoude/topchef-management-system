from app.modules.menu import repository, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ValidationError, NotFoundError
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select
from app.core.enums import ProductType 
from app.core.logging import logger

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
            logger.info(f"Menu Category created: '{category_data.cat_name}'")

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
            logger.info(f"Menu Category updated: id={cat_id}, new_name='{cat_data.cat_name}'")

        return schemas.CategoryResponse.from_orm(updatecat)

    async def delete_category(self, category_id: int):
        async with self.db.begin():
            category = await self.get_category(category_id)
            await self.repo.delete_category(category)
            logger.info(f"Menu Category deleted: id={category_id}, name='{category.cat_name}'")
        return True

    async def toggle_category(self, category_id: int):
        async with self.db.begin():
            category = await self.get_category(category_id)
            toggle = await self.repo.toggle_active(category)
            logger.info(f"Menu Category status toggled: id={category_id}, now_active={toggle.is_active}")

        return schemas.CategoryResponse.from_orm(toggle)


# ============== product ===============#
class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = repository.ProductRepository(db)
        self.varrepo = repository.VariantRepository(db)
        self.category_service = CategoryService(db)

    async def get_product(self, product_id: int):
        product = await self.repo.get_by_id(product_id)
        if not product or not product.is_available or not product.category.is_active:
            raise NotFoundError(f"Product With id:{product_id}")

        stmt = select(models.Product).options(selectinload(
            models.Product.variants)).where(models.Product.id == product_id)
        result = await self.db.execute(stmt)
        product_with_var = result.all()
        return product

    async def get_product_by_name(self, product_name: str):
        stmt = select(models.Product).options(selectinload(
            models.Product.variants)).where(models.Product.product_name == product_name)
        result = await self.db.execute(stmt)
        product_with_var = result.all()
        return product_with_var

    async def list_products(self):
        stmt = select(models.Product).join(models.Product.category).options(
            selectinload(models.Product.variants)).where(
                models.Category.is_deleted == False,
                models.Category.is_active == True
            )
        result = await self.db.execute(stmt)
        listproduct = result.scalars().all()
        return [schemas.ProductResponse.from_orm(c) for c in listproduct]

    async def create_product(self, product_data: schemas.CreateProduct):
        async with self.db.begin():
            product = await self.repo.get_by_name(product_data.product_name)
            cat = await self.category_service.get_category(product_data.cat_id)
            if product:
                raise ValidationError(
                    f"Product with name: '{product_data.product_name}' already exist")

            if product_data.product_type == ProductType.SIMPLE and len(product_data.variants) != 1:
                raise ValidationError(
                    "simple type of product must have one variant"
                )
            if product_data.product_type == ProductType.VARIANT and len(product_data.variants) < 2:
                raise ValidationError(
                    "variant type of product must have at least two variants"
                )

            product_model = models.Product(
                cat_id=product_data.cat_id,
                product_name=product_data.product_name,
                product_type=product_data.product_type,
                description=product_data.description

            )
            await self.repo.create_product(product_model)
            await self.db.flush()
            variants = []
            for v in product_data.variants:
                variant = models.Variant(
                    product_id=product_model.id,
                    name=v.name,
                    price=v.price
                )
                variants.append(variant)
            await self.varrepo.create_variant(variants)
            await self.db.flush()
            stmt = select(models.Product).options(
                selectinload(models.Product.category),
                selectinload(models.Product.variants)
            ).where(models.Product.id == product_model.id)
            result = await self.db.execute(stmt)
            product_with_relation = result.scalar_one()
            logger.info(f"Menu Product created: '{product_data.product_name}', type={product_data.product_type}")
        return schemas.ProductResponse.from_orm(product_with_relation)

    async def update_product(self, product_id: int, product_data: schemas.UpdateProduct):
        async with self.db.begin():
            existing = await self.repo.get_by_id(product_id)
            if not existing:
                raise NotFoundError(f"product with id:{product_id}")
            if product_data.cat_id is not None:
                cat = await self.category_service.get_category(product_data.cat_id)

            if product_data.product_name is not None:
                product = await self.repo.get_by_name(product_data.product_name)
                if product and product.id != product_id:
                    raise ValidationError(
                        f"Product with name: '{product_data.product_name}' already exist")

            if product_data.product_type == ProductType.SIMPLE and len(product_data.variants) != 1:
                raise ValidationError(
                    "simple type of product must have one variant"
                )
            if product_data.product_type == ProductType.VARIANT and len(product_data.variants) < 2:
                raise ValidationError(
                    "variant type of product must have at least two variants"
                )

            
            await self.repo.update_product(existing, product_data)
            if product_data.variants is not None:
                await self.varrepo.delete_by_product_id(product_id)
            await self.db.flush()
            if product_data.variants:
                variants = []
                for v in product_data.variants:
                    variant = models.Variant(
                        product_id= product_id,
                        name=v.name,
                        price=v.price
                    )
                    variants.append(variant)
                await self.varrepo.create_variant(variants)
                await self.db.flush()
            stmt = select(models.Product).options(
                selectinload(models.Product.category),
                selectinload(models.Product.variants)
            ).where(models.Product.id == product_id)
            result = await self.db.execute(stmt)
            product_with_relation = result.scalar_one()
            logger.info(f"Menu Product updated: id={product_id}")
        return schemas.ProductResponse.from_orm(product_with_relation)

    async def delete_product(self, product_id: int):
        async with self.db.begin():
            product = await self.get_product(product_id)
            await self.repo.delete_product(product)
            logger.info(f"Menu Product deleted: id={product_id}, name='{product.product_name}'")
        return True

    async def toggle_product(self, product_id: int):
        async with self.db.begin():
            product = await self.get_product(product_id)
            toggle = await self.repo.toggle_active(product)
            await self.db.flush()
            stmt = select(models.Product).options(
                selectinload(models.Product.category),
                selectinload(models.Product.variants)
            ).where(models.Product.id == product_id)
            result = await self.db.execute(stmt)
            product_with_relation = result.scalar_one()
            logger.info(f"Menu Product status toggled: id={product_id}, now_available={toggle.is_available}")
        return schemas.ProductResponse.from_orm(product_with_relation)


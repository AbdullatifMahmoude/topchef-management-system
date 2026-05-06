import json
import contextlib
from app.modules.menu import repository, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ValidationError, NotFoundError
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select
from app.core.enums import ProductType 
from app.core.logging import logger

# ============== category ===============#
class CategoryService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repo = repository.CategoryRepository(db)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def get_category(self, category_id: int, check_cache: bool = True, only_active: bool = False):
        # 1. Try Cache Path (Only for public active-only requests)
        if check_cache and only_active and self.redis:
            try:
                cached = await self.redis.get("menu:categories")
                if cached:
                    logger.info("⚡ Redis Cache Hit: Categories")
                    data = json.loads(cached)
                    for cat_data in data:
                        if cat_data["id"] == category_id:
                            return schemas.CategoryResponse.model_validate(cat_data)
            except Exception as e:
                logger.warning(f"Redis error getting category {category_id}: {e}")

        # 2. Database Path
        category = await self.repo.get_by_id(category_id)

        if not category:
            raise NotFoundError(f"Category with id:{category_id}")
            
        if only_active and not category.is_active:
             raise NotFoundError(f"Category with id:{category_id} is inactive")

        return category

    async def get_category_by_name(self, cat_name: str):
        cat = await self.repo.get_by_name(cat_name)
        return cat

    async def list_categories(self, only_active: bool = False):
        cache_key = "menu:categories"
        
        # 1. Try Cache (Only for public requests)
        if only_active and self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info("⚡ Redis Cache Hit: Category List")
                    data = json.loads(cached)
                    return [schemas.CategoryResponse.model_validate(item) for item in data]
            except Exception as e:
                logger.warning(f"Redis error reading categories: {e}")

        # 2. DB Fallback
        listcat = await self.repo.list_category(only_active=only_active)
        
        # Convert to schemas
        categories = [schemas.CategoryResponse.model_validate(c) for c in listcat]

        if only_active:
            # Refresh public cache
            if self.redis:
                try:
                    serializable = [c.model_dump(mode='json') for c in categories]
                    await self.redis.setex(cache_key, 3600, json.dumps(serializable))
                except Exception as e:
                    logger.warning(f"Redis error writing categories: {e}")

        return categories

    async def _invalidate_cache(self):
        if self.redis:
            try:
                await self.redis.delete("menu:categories")
                await self.redis.delete("menu:products")
            except Exception as e:
                logger.warning(f"Redis error invalidating menu cache: {e}")

    async def create_category(self, category_data: schemas.CreateCategory):
        async with self._transaction_scope():
            existing = await self.repo.get_by_name(category_data.cat_name)
            if existing:
                raise ValidationError(f"Category '{category_data.cat_name}' already exists")

            createcat = await self.repo.create_category(category_data)
            await self.db.flush()
            logger.info(f"Menu Category created: '{category_data.cat_name}'")
            await self._invalidate_cache()

        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "CATEGORY_UPDATED", "data": {"id": createcat.id, "cat_name": createcat.cat_name}})
        return schemas.CategoryResponse.model_validate(createcat)

    async def update_category(self, cat_id: int, cat_data: schemas.UpdateCategory):
        async with self._transaction_scope():
            existing = await self.get_category(cat_id, check_cache=False)

            if cat_data.cat_name is not None and cat_data.cat_name != existing.cat_name:
                exist_name = await self.repo.get_by_name(cat_data.cat_name)
                if exist_name:
                    raise ValidationError(f"Category '{cat_data.cat_name}' already exists")

            updatecat = await self.repo.update_category(existing, cat_data)
            await self.db.flush()
            logger.info(f"Menu Category updated: id={cat_id}")
            await self._invalidate_cache()

        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "CATEGORY_UPDATED", "data": {"id": updatecat.id, "cat_name": updatecat.cat_name}})
        return schemas.CategoryResponse.model_validate(updatecat)

    async def delete_category(self, category_id: int):
        from sqlalchemy.exc import IntegrityError
        try:
            async with self._transaction_scope():
                category = await self.get_category(category_id, check_cache=False)
                await self.repo.delete_category(category)
                await self.db.flush()
                logger.info(f"Menu Category deleted: id={category_id}")
                await self._invalidate_cache()
            return True
        except IntegrityError as e:
            if "foreign key" in str(e).lower() or "order_items" in str(e).lower():
                raise ValidationError("Cannot delete category because it contains products referenced in existing orders. Please disable its availability instead.")
            raise e

    async def toggle_category(self, category_id: int):
        async with self._transaction_scope():
            category = await self.get_category(category_id, check_cache=False)
            toggle = await self.repo.toggle_active(category)
            await self.db.flush()
            logger.info(f"Menu Category status toggled: id={category_id}, now_active={toggle.is_active}")
            await self._invalidate_cache()

        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "CATEGORY_UPDATED", "data": {"id": toggle.id, "cat_name": toggle.cat_name}})
        return schemas.CategoryResponse.model_validate(toggle)


# ============== product ===============#
class ProductService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repo = repository.ProductRepository(db)
        self.varrepo = repository.VariantRepository(db)
        self.category_service = CategoryService(db, redis)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def _invalidate_cache(self):
        if self.redis:
            try:
                await self.redis.delete("menu:products")
            except Exception as e:
                logger.warning(f"Redis error invalidating products cache: {e}")

    async def get_product(self, product_id: int, check_cache: bool = True, only_active: bool = False):
        # 1. Try Cache Path (Used strictly for public active-only requests)
        if check_cache and only_active and self.redis:
            try:
                cached = await self.redis.get("menu:products")
                if cached:
                    logger.info(f"⚡ Redis Cache Hit: Product {product_id}")
                    products = json.loads(cached)
                    for prod_data in products:
                        if prod_data["id"] == product_id:
                            return schemas.ProductResponse.model_validate(prod_data)
            except Exception as e:
                logger.warning(f"Redis error getting product {product_id}: {e}")

        # 2. Database Path
        product = await self.repo.get_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product With id:{product_id}")
        
        # Validation for public route if requested
        if only_active and (not product.is_available or not (product.category and product.category.is_active)):
            raise NotFoundError(f"Product With id:{product_id} is not available")
            
        return product

    async def get_products_by_ids(self, product_ids: list[int]) -> list[models.Product]:
        """Get multiple products by IDs."""
        return await self.repo.get_by_ids(product_ids)

    async def list_products(self, only_active: bool = False):
        cache_key = "menu:products"

        # 1. Try Cache (Only for public active-only requests)
        if only_active and self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info("⚡ Redis Cache Hit: Product List")
                    data = json.loads(cached)
                    return [schemas.ProductResponse.model_validate(item) for item in data]
            except Exception as e:
                logger.warning(f"Redis error reading products: {e}")

        # 2. DB Fallback
        listproduct = await self.repo.list_products(only_active=only_active)
        
        # Convert to schemas
        products = [schemas.ProductResponse.model_validate(p) for p in listproduct]

        if only_active:
            # Save public list to cache
            if self.redis:
                try:
                    serializable = [p.model_dump(mode='json') for p in products]
                    await self.redis.setex(cache_key, 3600, json.dumps(serializable))
                except Exception as e:
                    logger.warning(f"Redis error writing products: {e}")

        return products

    async def create_product(self, product_data: schemas.CreateProduct):
        async with self._transaction_scope():
            # Bundle checks into fewer DB trips
            existing = await self.repo.get_by_name(product_data.product_name, product_data.cat_id)
            
            if existing:
                raise ValidationError(f"Product name '{product_data.product_name}' already exists in this category")

            # Use cached category check for speed
            await self.category_service.get_category(product_data.cat_id)

            if product_data.product_type == ProductType.SIMPLE and len(product_data.variants) != 1:
                raise ValidationError("Simple type must have one variant")
            if product_data.product_type == ProductType.VARIANT and len(product_data.variants) < 2:
                raise ValidationError("Variant type must have at least two variants")

            # Efficient relationship management: build tree and save once
            product_model = models.Product(
                cat_id=product_data.cat_id,
                product_name=product_data.product_name,
                product_type=product_data.product_type,
                description=product_data.description,
                variants=[models.Variant(name=v.name, price=v.price) for v in product_data.variants]
            )
            await self.repo.create_product(product_model)
            await self.db.flush()
            logger.info(f"Menu Product created: '{product_data.product_name}'")
            await self._invalidate_cache()

        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "PRODUCT_UPDATED", "data": schemas.ProductResponse.model_validate(product_model).model_dump(mode='json')})
        return schemas.ProductResponse.model_validate(product_model)

    async def update_product(self, product_id: int, product_data: schemas.UpdateProduct):
        async with self._transaction_scope():
            # 1 DB Trip: Fetch product with category and variants pre-loaded
            existing = await self.get_product(product_id, check_cache=False)
            
            target_cat_id = product_data.cat_id if product_data.cat_id else existing.cat_id
            target_name = product_data.product_name if product_data.product_name else existing.product_name

            if product_data.cat_id and product_data.cat_id != existing.cat_id:
                await self.category_service.get_category(product_data.cat_id)

            if target_name != existing.product_name or target_cat_id != existing.cat_id:
                name_check = await self.repo.get_by_name(target_name, target_cat_id)
                if name_check and name_check.id != existing.id:
                    raise ValidationError(f"Product name '{target_name}' taken in this category")

            # Variant & Type Validation
            p_type = product_data.product_type or existing.product_type
            v_list = product_data.variants if product_data.variants is not None else existing.variants
            v_count = len(v_list)

            if p_type == ProductType.SIMPLE and v_count != 1:
                raise ValidationError(f"Simple type product must have exactly one variant (current count: {v_count})")
            
            if p_type == ProductType.VARIANT and v_count < 2:
                raise ValidationError(f"Variant type product must have at least two variants (current count: {v_count})")

            # Update core fields
            await self.repo.update_product(existing, product_data)
            
            # Efficient Variant update (if provided)
            if product_data.variants is not None:
                existing.variants = [models.Variant(name=v.name, price=v.price) for v in product_data.variants]

            await self.db.flush()
            logger.info(f"Menu Product updated: id={product_id}")
            await self._invalidate_cache()
            
        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "PRODUCT_UPDATED", "data": schemas.ProductResponse.model_validate(existing).model_dump(mode='json')})
        return schemas.ProductResponse.model_validate(existing)

    async def delete_product(self, product_id: int):
        from sqlalchemy.exc import IntegrityError
        try:
            async with self._transaction_scope():
                product = await self.get_product(product_id, check_cache=False)
                await self.repo.delete_product(product)
                await self.db.flush()
                logger.info(f"Menu Product deleted: id={product_id}")
                await self._invalidate_cache()
            return True
        except IntegrityError as e:
            if "foreign key" in str(e).lower() or "order_items" in str(e).lower():
                raise ValidationError("Cannot delete product because it is referenced in existing orders. Please disable its availability instead.")
            raise e

    async def toggle_product(self, product_id: int):
        async with self._transaction_scope():
            product = await self.get_product(product_id, check_cache=False)
            toggle = await self.repo.toggle_active(product)
            await self.db.flush()
            logger.info(f"Menu Product status toggled: id={product_id}, now_available={toggle.is_available}")
            await self._invalidate_cache()
            
        from app.core.events import order_events_manager
        order_events_manager.emit({"type": "PRODUCT_UPDATED", "data": schemas.ProductResponse.model_validate(toggle).model_dump(mode='json')})
        return schemas.ProductResponse.model_validate(toggle)


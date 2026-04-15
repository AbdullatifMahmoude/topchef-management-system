import json
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.modules.customer.repository import CustomerRepository
from app.modules.customer import models, schemas
from app.core.exceptions import NotFoundError, ValidationError

class CustomerService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.repository = CustomerRepository(db)
        self.redis = redis

    async def create_customer(self, customer_data: schemas.CustomerCreate) -> models.Customer:
        """Atomic customer creation with phone uniqueness check."""
        async with self.db.begin():
            # 1. Business Validation
            existing = await self.repository.get_by_phone(customer_data.phone_number)
            if existing:
                raise ValidationError(f"Customer with phone {customer_data.phone_number} already exists")
            
            # 2. Model Instantiation (Service owns this now)
            new_customer = models.Customer(**customer_data.model_dump())
            
            # 3. Save via Repository
            customer = await self.repository.save(new_customer)
            
            # Invalidate any list caches if they exist
            await self._invalidate_cache(f"customer_at_phone:{customer.phone_number}")
            return customer

    async def get_customer(self, customer_id: int) -> models.Customer:
        # 1. Try Cache
        cache_key = f"customer_profile:{customer_id}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return models.Customer(**json.loads(cached))
            except Exception:
                pass

        # 2. Get DB
        customer = await self.repository.get_by_id(customer_id)
        if not customer:
            raise NotFoundError(f"Customer with id {customer_id} not found")
        
        # 3. Cache
        if self.redis:
            try:
                # We convert to dict for storage, careful with datetime
                data = schemas.CustomerResponse.model_validate(customer).model_dump_json()
                await self.redis.setex(cache_key, 3600, data)
            except Exception:
                pass
        
        return customer

    async def get_customer_by_phone(self, phone: str) -> models.Customer:
        # 1. Try Cache
        cache_key = f"customer_at_phone:{phone}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return models.Customer(**json.loads(cached))
            except Exception:
                pass

        # 2. Get DB
        customer = await self.repository.get_by_phone(phone)
        if not customer:
            raise NotFoundError(f"Customer with phone {phone} not found")
        
        # 3. Cache
        if self.redis:
            try:
                data = schemas.CustomerResponse.model_validate(customer).model_dump_json()
                await self.redis.setex(cache_key, 3600, data)
            except Exception:
                pass
                
        return customer

    async def add_address(self, customer_id: int, address_data: schemas.CustomerAddressCreate) -> models.CustomerAddress:
        """Atomic address addition."""
        async with self.db.begin():
            # 1. Validation
            customer = await self.repository.get_by_id(customer_id)
            if not customer:
                raise NotFoundError(f"Customer with id {customer_id} not found")
            
            # 2. Model Instantiation
            new_address = models.CustomerAddress(
                customer_id=customer_id, 
                **address_data.model_dump()
            )
            
            # 3. Save
            address = await self.repository.save(new_address)
            
            # 4. Invalidate Customer cache (since addresses changed)
            if self.redis:
                await self.redis.delete(f"customer_profile:{customer_id}")
                await self.redis.delete(f"customer_at_phone:{customer.phone_number}")
            
            return address

    async def _invalidate_cache(self, key: str):
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass

    async def list_customers(self) -> List[models.Customer]:
        return await self.repository.list_customers()

from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.modules.customer.repository import CustomerRepository
from app.modules.customer import models, schemas
from app.modules.customer.phone import normalize_egyptian_phone
from app.core.exceptions import NotFoundError, ValidationError
import contextlib

class CustomerService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.repository = CustomerRepository(db)
        self.redis = redis

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def create_customer(self, customer_data: schemas.CustomerCreate) -> models.Customer:
        """Atomic customer creation with phone uniqueness check."""
        async with self._transaction_scope():
            payload = customer_data.model_dump()
            payload["phone_number"] = normalize_egyptian_phone(payload.get("phone_number")) or (
                payload.get("phone_number") or ""
            ).strip()

            # 1. Business Validation
            existing = await self.repository.get_by_phone(payload["phone_number"])
            if existing:
                raise ValidationError(f"Customer with phone {payload['phone_number']} already exists")
            
            # 2. Model Instantiation (Service owns this now)
            new_customer = models.Customer(**payload)
            
            # 3. Save via Repository
            customer = await self.repository.save(new_customer)
            
        
        # 5. Reload with eager loading after transaction commits
        reloaded_customer = await self.repository.get_by_id(customer.id)
        
        # 6. Emit real-time event for WebSocket subscribers
        try:
            from app.core.events import order_events_manager
            import asyncio
            asyncio.ensure_future(order_events_manager.emit({
                "type": "CUSTOMER_CREATED",
                "data": {
                    "id": reloaded_customer.id,
                    "name": reloaded_customer.name,
                    "phone_number": reloaded_customer.phone_number,
                }
            }))
        except Exception:
            pass
        
        # 7. Invalidate any list caches if they exist
        await self._invalidate_cache(f"customer_at_phone:{reloaded_customer.phone_number}")
        return reloaded_customer

    async def get_customer(self, customer_id: int) -> models.Customer:
        # Always load from DB so callers get a session-bound ORM with addresses.
        # (Rebuilding Customer from Redis JSON dropped addresses and broke mutations.)
        customer = await self.repository.get_by_id(customer_id)
        if not customer:
            raise NotFoundError(f"Customer with id {customer_id} not found")
        
        if self.redis:
            try:
                data = schemas.CustomerResponse.model_validate(customer).model_dump_json()
                await self.redis.setex(f"customer_profile:{customer_id}", 3600, data)
            except Exception:
                pass
        
        return customer

    async def get_customer_by_phone(self, phone: str) -> models.Customer:
        normalized = normalize_egyptian_phone(phone) or (phone or "").strip()
        customer = await self.repository.get_by_phone(normalized or phone)
        if not customer:
            raise NotFoundError(f"Customer with phone {phone} not found")
        
        if self.redis:
            try:
                data = schemas.CustomerResponse.model_validate(customer).model_dump_json()
                await self.redis.setex(f"customer_at_phone:{customer.phone_number}", 3600, data)
                if normalized and normalized != customer.phone_number:
                    await self.redis.setex(f"customer_at_phone:{normalized}", 3600, data)
            except Exception:
                pass
                
        return customer

    async def add_address(self, customer_id: int, address_data: schemas.CustomerAddressCreate) -> models.CustomerAddress:
        """Atomic address addition with deduplication."""
        async with self._transaction_scope():
            # 1. Validation
            customer = await self.repository.get_by_id(customer_id)
            if not customer:
                raise NotFoundError(f"Customer with id {customer_id} not found")
            
            # 2. Deduplication: check if this exact address already exists for this customer
            from sqlalchemy import select
            existing_addr_result = await self.db.execute(
                select(models.CustomerAddress).where(
                    models.CustomerAddress.customer_id == customer_id,
                    models.CustomerAddress.address == address_data.address,
                    models.CustomerAddress.is_deleted == False
                )
            )
            existing_addr = existing_addr_result.scalars().first()
            if existing_addr:
                # Address already exists — return it without creating a duplicate
                return existing_addr
            
            # 3. Model Instantiation
            new_address = models.CustomerAddress(
                customer_id=customer_id, 
                **address_data.model_dump()
            )
            
            # 4. Save
            address = await self.repository.save(new_address)
            
            # 6. Emit real-time event for WebSocket subscribers
            try:
                from app.core.events import order_events_manager
                import asyncio
                asyncio.ensure_future(order_events_manager.emit({
                    "type": "ADDRESS_CREATED",
                    "data": {
                        "id": address.id,
                        "customer_id": customer_id,
                        "address": address_data.address,
                    }
                }))
            except Exception:
                pass
            
            # 7. Invalidate Customer cache (since addresses changed)
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

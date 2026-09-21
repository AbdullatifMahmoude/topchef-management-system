from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.customer import models
from app.modules.customer.phone import phone_lookup_candidates


class CustomerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _address_load_option(self):
        return selectinload(
            models.Customer.addresses.and_(models.CustomerAddress.is_deleted == False)
        )

    async def get_by_id(self, customer_id: int) -> Optional[models.Customer]:
        query = (
            select(models.Customer)
            .where(
                models.Customer.id == customer_id,
                models.Customer.is_deleted == False
            )
            .options(self._address_load_option())
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_basic_by_id(self, customer_id: int) -> Optional[models.Customer]:
        result = await self.db.execute(
            select(models.Customer).where(
                models.Customer.id == customer_id,
                models.Customer.is_deleted == False,
            )
        )
        return result.scalars().first()

    async def get_by_phone(self, phone: str) -> Optional[models.Customer]:
        candidates = phone_lookup_candidates(phone)
        if not candidates:
            return None
        query = (
            select(models.Customer)
            .where(
                models.Customer.phone_number.in_(candidates),
                models.Customer.is_deleted == False
            )
            .options(self._address_load_option())
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[models.Customer]:
        query = (
            select(models.Customer)
            .where(
                models.Customer.email == email.strip().lower(),
                models.Customer.is_deleted == False,
            )
            .options(self._address_load_option())
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def save(self, obj) -> any:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_customers(self) -> List[models.Customer]:
        query = (
            select(models.Customer)
            .where(models.Customer.is_deleted == False)
            .options(self._address_load_option())
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def delete_customer(self, customer: models.Customer):
        import time
        ts = int(time.time())
        customer.is_deleted = True
        # Keep under column length while freeing the original phone for reuse
        base = (customer.phone_number or "")[:20]
        customer.phone_number = f"{base}_d{ts}"
        if customer.email:
            local, _, domain = customer.email.partition("@")
            customer.email = f"{local[:180]}+deleted-{ts}@{domain}"[:254]
        # Also soft delete addresses
        for addr in customer.addresses:
            addr.is_deleted = True

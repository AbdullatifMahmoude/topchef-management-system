from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from app.modules.customer import models

class CustomerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, customer_id: int) -> Optional[models.Customer]:
        query = (
            select(models.Customer)
            .where(
                models.Customer.id == customer_id,
                models.Customer.is_deleted == False
            )
            .options(selectinload(models.Customer.addresses))
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, phone: str) -> Optional[models.Customer]:
        query = (
            select(models.Customer)
            .where(
                models.Customer.phone_number == phone,
                models.Customer.is_deleted == False
            )
            .options(selectinload(models.Customer.addresses))
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
            .options(selectinload(models.Customer.addresses))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def delete_customer(self, customer: models.Customer):
        import time
        ts = int(time.time())
        customer.is_deleted = True
        customer.phone_number = f"{customer.phone_number}_deleted_{ts}"
        # Also soft delete addresses
        for addr in customer.addresses:
            addr.is_deleted = True

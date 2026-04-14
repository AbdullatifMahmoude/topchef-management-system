from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from app.modules.customer import models

class CustomerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, customer_id: int) -> Optional[models.Customer]:
        query = select(models.Customer).where(models.Customer.id == customer_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, phone: str) -> Optional[models.Customer]:
        query = select(models.Customer).where(models.Customer.phone_number == phone)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def save(self, obj) -> any:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_customers(self) -> List[models.Customer]:
        query = select(models.Customer)
        result = await self.db.execute(query)
        return result.scalars().all()

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.core.redis import get_redis
from app.modules.customer.service import CustomerService
from app.modules.customer import schemas

router = APIRouter(prefix="/customers", tags=["Customers"])

@router.post("/", response_model=schemas.CustomerResponse)
async def create_customer(
    customer_data: schemas.CustomerCreate,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    current_user: any = Depends(get_current_user)
):
    service = CustomerService(db, redis=redis)
    return await service.create_customer(customer_data)

@router.get("/", response_model=List[schemas.CustomerResponse])
async def list_customers(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    current_user: any = Depends(get_current_user)
):
    service = CustomerService(db, redis=redis)
    return await service.list_customers()

@router.get("/{customer_id}", response_model=schemas.CustomerResponse)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    current_user: any = Depends(get_current_user)
):
    service = CustomerService(db, redis=redis)
    return await service.get_customer(customer_id)

@router.get("/by-phone/{phone}", response_model=schemas.CustomerResponse)
async def get_customer_by_phone(
    phone: str,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    current_user: any = Depends(get_current_user)
):
    service = CustomerService(db, redis=redis)
    return await service.get_customer_by_phone(phone)

@router.post("/{customer_id}/addresses", response_model=schemas.CustomerAddressResponse)
async def add_address(
    customer_id: int,
    address_data: schemas.CustomerAddressCreate,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    current_user: any = Depends(get_current_user)
):
    service = CustomerService(db, redis=redis)
    return await service.add_address(customer_id, address_data)

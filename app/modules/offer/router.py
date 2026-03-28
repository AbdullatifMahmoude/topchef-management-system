from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.offer import service, schemas
from typing import List
from app.modules.infrastructure.dependencies import (
    require_capability,
    Capability,
    get_current_user,
)

router = APIRouter(prefix="/offers", tags=["offers"])

@router.get("/", response_model=List[schemas.OfferResponse])
async def list_offers(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.VIEW_OFFERS)),
):
    offer_service = service.OfferService(db)
    return await offer_service.list_all_offers()

@router.post("/", response_model=schemas.OfferResponse, status_code=status.HTTP_201_CREATED)
async def create_offer(
    offer_data: schemas.OfferCreate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.MANAGE_OFFERS)),
):
    offer_service = service.OfferService(db)
    return await offer_service.create_offer(offer_data)

@router.get("/{offer_id}", response_model=schemas.OfferResponse)
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.VIEW_OFFERS)),
):
    offer_service = service.OfferService(db)
    return await offer_service.get_offer_by_id(offer_id)

@router.get("/code/{code}", response_model=schemas.OfferResponse)
async def get_offer_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.VIEW_OFFERS)),
):
    offer_service = service.OfferService(db)
    return await offer_service.get_offer_by_code(code)

@router.patch("/{offer_id}", response_model=schemas.OfferResponse)
async def update_offer(
    offer_id: int,
    offer_data: schemas.OfferUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.MANAGE_OFFERS)),
):
    offer_service = service.OfferService(db)
    return await offer_service.update_offer(offer_id, offer_data)

@router.delete("/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_capability(Capability.MANAGE_OFFERS)),
):
    offer_service = service.OfferService(db)
    await offer_service.delete_offer(offer_id)
    return None

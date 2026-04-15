from fastapi import APIRouter, Depends
from app.core.exceptions import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.pricing import schemas, service
from app.modules.auth.dependencies import get_optional_user
from app.modules.users.schemas import UserResponse
from typing import Optional

router = APIRouter(prefix="/pricing", tags=["Pricing"])

from app.modules.orders.dependencies import get_pricing_service

@router.post("/preview", response_model=schemas.PricingResult)
async def get_price_preview(
    request: schemas.PricingRequest,
    pricing_service: service.PricingService = Depends(get_pricing_service),
    current_user: Optional[UserResponse] = Depends(get_optional_user)
):
    """
    Public endpoint to preview pricing and offers.
    Security: Includes IDOR protection to prevent phone-probing.
    """
    # IDOR Protection: If user is logged in, they must probe their own phone or be staff
    if current_user:
        # Check if user is staff (admin or cashier)
        is_staff = any(role.name.lower() in ["admin", "cashier"] for role in getattr(current_user, 'roles', []))
        
        # If not staff, enforce that the requested phone matches the user's own phone
        if not is_staff and request.customer_phone:
            user_phone = getattr(current_user, 'phone', None)
            if user_phone and request.customer_phone != user_phone:
                from app.core.logging import logger
                logger.warning(f"IDOR attempt: User {current_user.id} tried to probe phone {request.customer_phone}")
                # We return a generic error or just override the phone to theirs
                # For security, raising ValidationError is better to signal it's blocked
                raise ValidationError("You can only preview pricing for your own phone number.")

    return await pricing_service.calculate_price(request)

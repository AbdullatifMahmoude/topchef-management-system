from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from app.core.exceptions import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.pricing import schemas, service
from app.modules.auth.dependencies import get_optional_user
from app.modules.users.schemas import UserResponse
from typing import Optional
import time
from collections import defaultdict

router = APIRouter(prefix="/pricing", tags=["Pricing"])

from app.modules.orders.dependencies import get_pricing_service

# In-memory rate limiter for pricing preview (per-IP sliding window)
_pricing_rate_limit: dict[str, list[float]] = defaultdict(list)
_PRICING_RATE_LIMIT_MAX = 5       # max requests
_PRICING_RATE_LIMIT_WINDOW = 60   # per window (seconds)


def _check_rate_limit(client_ip: str) -> bool:
    """Returns True if the request should be allowed, False if rate-limited."""
    now = time.monotonic()
    timestamps = _pricing_rate_limit[client_ip]
    # Prune entries outside the window
    _pricing_rate_limit[client_ip] = [t for t in timestamps if now - t < _PRICING_RATE_LIMIT_WINDOW]
    if len(_pricing_rate_limit[client_ip]) >= _PRICING_RATE_LIMIT_MAX:
        return False
    _pricing_rate_limit[client_ip].append(now)
    return True


@router.post("/preview", response_model=schemas.PricingResult)
async def get_price_preview(
    request: schemas.PricingRequest,
    http_request: Request = None,
    pricing_service: service.PricingService = Depends(get_pricing_service),
    current_user: Optional[UserResponse] = Depends(get_optional_user)
):
    """
    Public endpoint to preview pricing and offers.
    Security: Includes IDOR protection to prevent phone-probing and rate limiting.
    """
    # Rate limiting
    client_ip = "unknown"
    if http_request:
        client_ip = http_request.client.host if http_request.client else "unknown"
    if not _check_rate_limit(client_ip):
        from app.core.logging import logger
        logger.warning("Rate limit exceeded for pricing preview from IP: %s", client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."}
        )

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

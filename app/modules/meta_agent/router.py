from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppExceptions
from app.modules.meta_agent import schemas, service
from app.modules.meta_agent.auth import require_meta_agent_key

router = APIRouter(
    prefix="/integrations/meta-agent/v1",
    tags=["Meta Business Agent"],
    dependencies=[Depends(require_meta_agent_key)],
)


def _readiness_payload() -> dict[str, str]:
    return {
        "status": "ready",
        "integration": "meta-business-agent",
        "version": "v1",
    }


@router.get("")
async def meta_agent_root() -> dict[str, str]:
    """Authenticated connector base URL probe used by Meta during setup."""
    return _readiness_payload()


@router.get("/health")
async def meta_agent_health() -> dict[str, str]:
    """Authenticated readiness probe for Meta connector configuration."""
    return _readiness_payload()


@router.get("/capabilities", response_model=schemas.AgentCapabilities)
async def meta_agent_capabilities() -> schemas.AgentCapabilities:
    """Declare the strict read-only boundary exposed to Meta Business Agent."""
    return schemas.AgentCapabilities(
        allowed=["menu_and_pricing", "order_status", "order_status_history"],
        handoff_required=["create_order", "update_order", "cancel_order"],
    )


@router.get("/menu", response_model=schemas.MenuResponse)
async def meta_agent_menu(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> schemas.MenuResponse:
    """Return only active, available menu products and their current prices."""
    return await service.get_available_menu(db)


@router.get("/orders/{order_number}/status", response_model=schemas.OrderTrackingResponse)
async def meta_agent_order_status(
    order_number: str,
    customer_phone: str = Query(
        min_length=10,
        max_length=20,
        description="WhatsApp sender phone used to verify order ownership",
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> schemas.OrderTrackingResponse:
    """Read order status only after matching it to the WhatsApp sender phone."""
    order = await service.get_owned_order_status(
        db,
        order_number=order_number,
        customer_phone=customer_phone,
    )
    if order is None:
        # Deliberately hide whether the order number exists for another customer.
        raise AppExceptions(
            status_code=404,
            detail="Order not found for this customer",
            error_code="ORDER_NOT_FOUND",
        )
    return order

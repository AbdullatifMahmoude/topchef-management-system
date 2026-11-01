from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.meta_agent.service import get_available_menu
from app.modules.offer.models import Offer


async def get_public_catalog(db: AsyncSession) -> dict:
    """Build the read-only catalog exposed to website knowledge crawlers."""
    menu = await get_available_menu(db)
    now = datetime.now(ZoneInfo("Africa/Cairo")).replace(tzinfo=None)
    result = await db.execute(
        select(Offer)
        .options(selectinload(Offer.products))
        .where(
            Offer.is_deleted.is_(False),
            Offer.is_active.is_(True),
            Offer.valid_from <= now,
            Offer.valid_to >= now,
            or_(Offer.usage_limit.is_(None), Offer.current_usage < Offer.usage_limit),
        )
        .order_by(Offer.display_name, Offer.code)
    )
    offers = []
    for offer in result.scalars().all():
        offers.append(
            {
                "name": offer.display_name or offer.code,
                "code": offer.code,
                "type": offer.discount_type.value,
                "value": offer.discount_value,
                "minimum": offer.min_order_amount,
                "maximum_discount": offer.max_discount_amount,
                "valid_to": offer.valid_to,
                "products": [product.product_name for product in offer.products],
                "rules": offer.rules or {},
            }
        )
    return {
        "generated_at": datetime.now(ZoneInfo("Africa/Cairo")),
        "currency": menu.currency,
        "products": menu.products,
        "offers": offers,
    }

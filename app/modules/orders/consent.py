from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderSource
from app.modules.customer.service import CustomerService


async def resolve_order_message_consent(db: AsyncSession, redis, order_data):
    """Snapshot whether this order may start or continue transactional messaging."""
    initial_contact_allowed = bool(
        order_data.whatsapp_initial_contact_allowed and order_data.source == OrderSource.ONLINE
    )
    if order_data.customer_id:
        customer = await CustomerService(db, redis).get_customer(order_data.customer_id)
        if customer.whatsapp_status == "enabled":
            initial_contact_allowed = True
        elif customer.whatsapp_status in {"pending", "disabled", "unavailable"}:
            initial_contact_allowed = False
    order_data.whatsapp_initial_contact_allowed = initial_contact_allowed
    return order_data

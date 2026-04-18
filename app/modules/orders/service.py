from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Tuple
from app.modules.orders.repository import OrderRepository
from app.modules.orders import schemas, models
from app.modules.pricing.service import PricingService
from app.modules.settings.service import SettingsService
from app.modules.pricing.schemas import PricingRequest, PricingItem
from app.modules.offer.service import OfferService
from app.core.exceptions import ValidationError, NotFoundError
from app.modules.auth.repository import AuthRepository

import contextlib

from app.core.protocols import PricingServiceInterface, OfferServiceInterface, CacheStore
from app.core.events import order_events_manager


class OrderService:
    def __init__(
        self, 
        db: AsyncSession, 
        redis: Optional[CacheStore] = None,
        pricing_service: Optional[PricingServiceInterface] = None,
        offer_service: Optional[OfferServiceInterface] = None
    ):
        self.db = db
        self.repository = OrderRepository(db)
        self.redis = redis
        self.pricing_service = pricing_service or PricingService(db)
        self.offer_service = offer_service or OfferService(db, redis=redis)
        self.settings_service = SettingsService(db, redis=redis)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def _validate_order_items(self, items: List[schemas.OrderItemCreate]):
        """Validate products exist and are available."""
        from app.modules.menu.service import ProductService
        
        product_ids = [item.product_id for item in items]
        if not product_ids:
            raise ValidationError("Order must have at least one item")
        
        menu_service = ProductService(self.db)
        products = await menu_service.get_products_by_ids(product_ids)
        products_by_id = {p.id: p for p in products}
        
        for item in items:
            if item.product_id not in products_by_id:
                raise ValidationError(f"Product ID {item.product_id} not found")
            
            product = products_by_id[item.product_id]
            if not product.is_available:
                raise ValidationError(f"'{product.product_name}' is currently unavailable")

    async def create_order(self, order_data: schemas.OrderCreate, current_user_id: Optional[int] = None) -> models.Order:
        """
        Creates an order with idempotency protection.
        """
        async with self._transaction_scope():
            # Check if online orders are enabled
            if order_data.source == models.OrderSource.ONLINE:
                if not await self.settings_service.get_web_orders_status():
                    raise ValidationError("Online ordering is currently disabled.")

            # ✅ NEW: Validate items first
            await self._validate_order_items(order_data.items)
            
            # 0. Check Idempotency Key
            if order_data.idempotency_key:
                existing = await self.repository.get_by_idempotency_key(order_data.idempotency_key)
                if existing:
                    return existing
            
            # 1. Prepare Pricing Request
            pricing_items = [
                PricingItem(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price
                ) for item in order_data.items
            ]
            
            pricing_req = PricingRequest(
                items=pricing_items,
                order_type=order_data.order_type,
                delivery_fee=order_data.delivery_fee,
                offer_code=order_data.offer_code,
                customer_phone=order_data.customer_phone,
                cashier_id=current_user_id if order_data.source == "cashier" else None
            )
            
            # 2. Get Pricing Calculation (Preview)
            pricing_res = await self.pricing_service.calculate_price(pricing_req)
            
            # ✅ FIX: Validate financial integrity before proceeding
            from decimal import Decimal
            if pricing_res.discount_amount < Decimal("0.00"):
                raise ValidationError("Invalid discount amount: negative discount detected")
            if pricing_res.discount_amount > pricing_res.subtotal:
                raise ValidationError("Invalid discount: discount exceeds subtotal")
            if pricing_res.total_amount < Decimal("0.00"):
                raise ValidationError("Invalid order: total amount cannot be negative")

            # 3. Create Order Object (Service now handles instantiation)
            next_number = await self.repository.get_next_order_number()
            
            order_dict = order_data.model_dump(exclude={'items', 'offer_code', 'source'})
            order = models.Order(**order_dict)
            
            # 4. Fill calculated financials and metadata
            order.order_number = next_number
            order.order_date = self.repository.get_business_date()
            order.order_source = order_data.source
            order.created_by_user_id = current_user_id
            
            if order.order_source == models.OrderSource.CASHIER:
                order.order_status = models.OrderStatus.CONFIRMED
            else:
                order.order_status = models.OrderStatus.NEW
            
            order.subtotal = pricing_res.subtotal
            order.discount_amount = pricing_res.discount_amount
            order.delivery_fee = pricing_res.delivery_fee
            order.total_amount = pricing_res.total_amount
            
            # 5. Add Items
            for item_data in order_data.items:
                item = models.OrderItem(**item_data.model_dump())
                item.total_price = item.quantity * item.unit_price
                order.items.append(item)
            
            # 6. Officially REDEEM the offer (Commit) if it exists
            if order_data.offer_code:
                # ✅ FIX: Flush order to database to generate 'order.id' for usage tracking
                self.db.add(order)
                await self.db.flush()
                
                await self.offer_service.apply_offer(
                    code=order_data.offer_code,
                    subtotal=pricing_res.subtotal,
                    items=pricing_items,
                    customer_phone=order_data.customer_phone,
                    cashier_id=current_user_id,
                    commit_usage=True,
                    order_id=order.id # Link to newly created order
                )
            
            # 7. Final Save (add + flush)
            order = await self.repository.save_in_transaction(order)
            
            # 8. Real-time Notification
            await order_events_manager.broadcast({
                "event": "order.created",
                "data": {
                    "id": order.id,
                    "order_number": order.order_number,
                    "source": order.order_source.value,
                    "status": order.order_status.value,
                    "total": str(order.total_amount)
                }
            })
            
            return order



    async def get_order(self, order_id: int) -> models.Order:
        order = await self.repository.get_by_id(order_id)
        if not order:
            raise NotFoundError(f"Order with ID {order_id}")
        return order

    async def list_orders_paginated(
        self,
        source: Optional[str] = None,
        status: Optional[str] = None,
        order_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[int, List[models.Order]]:
        """Paginated order listing with enrichment already handled by eager loading."""
        return await self.repository.list_orders_paginated(
            source=source,
            status=status,
            order_type=order_type,
            page=page,
            page_size=page_size
        )

    async def list_orders(self, **kwargs) -> List[models.Order]:
        """Listing with enrichment already handled by eager loading."""
        return await self.repository.list_orders(**kwargs)


    async def update_order_status(self, order_id: int, update_data: schemas.OrderUpdate, current_user_id: Optional[int] = None) -> models.Order:
        order = await self.get_order(order_id)
        updated_order = await self.repository.update(order, update_data, changed_by_user_id=current_user_id)
        
        # Real-time Notification for update
        await order_events_manager.broadcast({
            "event": "order.updated",
            "data": {
                "id": updated_order.id,
                "order_number": updated_order.order_number,
                "status": updated_order.order_status.value
            }
        })
        
        return updated_order


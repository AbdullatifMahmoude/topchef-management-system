from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Tuple
from app.modules.orders.repository import OrderRepository
from app.modules.orders import schemas, models
from app.modules.pricing.service import PricingService
from app.modules.settings.service import SettingsService
from app.modules.pricing.schemas import PricingRequest, PricingItem
from app.modules.offer.service import OfferService
from app.core.exceptions import ValidationError, NotFoundError
import contextlib
from decimal import Decimal

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

    def _record_outbox_event(self, event_type: str, data: dict):
        """Records an event in the outbox queue to be synced to the cloud if running in desktop mode."""
        import os
        import json
        if os.environ.get("RUNTIME_MODE") == "desktop":
            from app.modules.orders.models import OutboxEvent, OutboxEventStatus
            outbox_record = OutboxEvent(
                event_type=event_type,
                topic="orders.local",
                payload=json.dumps(data),
                status=OutboxEventStatus.PENDING
            )
            self.db.add(outbox_record)

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
        async with self._transaction_scope():
            # Check if online orders are enabled
            if order_data.source == models.OrderSource.ONLINE:
                if not await self.settings_service.get_web_orders_status():
                    raise ValidationError("Online ordering is currently disabled.")

            # Validate items
            await self._validate_order_items(order_data.items)
            
            # Idempotency check
            if order_data.idempotency_key:
                existing = await self.repository.get_by_idempotency_key(order_data.idempotency_key)
                if existing:
                    return existing
            
            # Auto-create or link customer
            if order_data.customer_phone and order_data.customer_name:
                from app.modules.customer.service import CustomerService
                from app.modules.customer.schemas import CustomerCreate, CustomerAddressCreate
                
                customer_service = CustomerService(self.db, self.redis)
                try:
                    existing_cust = await customer_service.get_customer_by_phone(order_data.customer_phone)
                    order_data.customer_id = existing_cust.id
                except NotFoundError:
                    new_cust = await customer_service.create_customer(CustomerCreate(
                        name=order_data.customer_name,
                        phone_number=order_data.customer_phone
                    ))
                    order_data.customer_id = new_cust.id
                
                if getattr(order_data, 'customer_address', None):
                    new_addr = await customer_service.add_address(order_data.customer_id, CustomerAddressCreate(address=order_data.customer_address))
                    order_data.address_id = new_addr.id
            
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
                cashier_id=current_user_id if order_data.source == models.OrderSource.CASHIER else None
            )
            
            # 2. Get Pricing Calculation
            pricing_res = await self.pricing_service.calculate_price(pricing_req)
            
            # 3. Create Order Object
            next_number = await self.repository.get_next_order_number()
            order_dict = order_data.model_dump(exclude={'items', 'offer_code', 'source', 'customer_address', 'order_number', 'order_date'})
            order = models.Order(**order_dict)
            
            # 4. Fill calculated financials and metadata
            order.order_number = getattr(order_data, 'order_number', None) or next_number
            order.order_date = getattr(order_data, 'order_date', None) or self.repository.get_business_date()
            order.order_source = order_data.source
            order.created_by_user_id = current_user_id
            
            if order_data.source == models.OrderSource.CASHIER:
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
            
            # 6. Officially REDEEM the offer if it exists
            if order_data.offer_code:
                self.db.add(order)
                await self.db.flush()
                await self.offer_service.apply_offer(
                    code=order_data.offer_code,
                    subtotal=pricing_res.subtotal,
                    items=pricing_items,
                    customer_phone=order_data.customer_phone,
                    cashier_id=current_user_id,
                    commit_usage=True,
                    order_id=order.id
                )
            
            # 7. Save and Refresh
            order = await self.repository.save_in_transaction(order)
            order = await self.get_order(order.id)
            
            # Record Outbox Event
            order_schema = schemas.OrderResponse.model_validate(order)
            payload_data = order_schema.model_dump(mode='json')
            self._record_outbox_event("ORDER_CREATED", payload_data)
            
            # 8. Trigger Sync and Notify
            from app.core.events import outbox_sync_trigger
            outbox_sync_trigger.set()
            order_events_manager.emit({
                "type": "NEW_ORDER",
                "event": "order.created",
                "data": payload_data
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
        return await self.repository.list_orders_paginated(
            source=source,
            status=status,
            order_type=order_type,
            page=page,
            page_size=page_size
        )

    async def list_orders(self, **kwargs) -> List[models.Order]:
        return await self.repository.list_orders(**kwargs)

    async def update_order_status(self, order_id: int, update_data: schemas.OrderUpdate, current_user_id: Optional[int] = None) -> models.Order:
        async with self._transaction_scope():
            order = await self.get_order(order_id)
            if update_data.order_status and order.order_status != update_data.order_status:
                if not order.can_transition_to(update_data.order_status):
                    raise ValidationError(f"Invalid status transition from {order.order_status} to {update_data.order_status}")
            
            updated_order = await self.repository.update(order, update_data, changed_by_user_id=current_user_id)
            completed_order = await self.get_order(updated_order.id)
            completed_schema = schemas.OrderResponse.model_validate(completed_order)
            payload_data = completed_schema.model_dump(mode='json')
            self._record_outbox_event("ORDER_UPDATED", payload_data)
        
        from app.core.events import outbox_sync_trigger
        outbox_sync_trigger.set()
        order_events_manager.emit({
            "type": "ORDER_UPDATED",
            "event": "order.updated",
            "data": payload_data
        })
        return completed_order

    async def update_order(self, order_id: int, update_data: schemas.OrderUpdateFull, current_user_id: Optional[int] = None) -> models.Order:
        async with self._transaction_scope():
            order = await self.get_order(order_id)
            if order.order_status in [models.OrderStatus.COMPLETED, models.OrderStatus.DELIVERED, models.OrderStatus.CANCELLED]:
                raise ValidationError(f"Cannot update an order that is {order.order_status.value}")
            
            if update_data.customer_phone or update_data.customer_name or getattr(update_data, 'customer_address', None):
                target_phone = update_data.customer_phone or order.customer_phone
                target_name = update_data.customer_name or order.customer_name
                if target_phone and target_name:
                    from app.modules.customer.service import CustomerService
                    from app.modules.customer.schemas import CustomerCreate, CustomerAddressCreate
                    customer_service = CustomerService(self.db, self.redis)
                    try:
                        existing_cust = await customer_service.get_customer_by_phone(target_phone)
                        update_data.customer_id = existing_cust.id
                    except NotFoundError:
                        new_cust = await customer_service.create_customer(CustomerCreate(
                            name=target_name,
                            phone_number=target_phone
                        ))
                        update_data.customer_id = new_cust.id
                    if getattr(update_data, 'customer_address', None):
                        new_addr = await customer_service.add_address(update_data.customer_id, CustomerAddressCreate(address=update_data.customer_address))
                        update_data.address_id = new_addr.id

            needs_reprice = False
            if update_data.delivery_fee is not None and update_data.delivery_fee != order.delivery_fee:
                order.delivery_fee = update_data.delivery_fee
                needs_reprice = True
            if update_data.items is not None:
                needs_reprice = True
            
            if needs_reprice:
                if update_data.items is not None:
                    await self._validate_order_items(update_data.items)
                    pricing_items = [PricingItem(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price) for it in update_data.items]
                else:
                    pricing_items = [PricingItem(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price) for it in order.items]
                
                pricing_req = PricingRequest(
                    items=pricing_items, order_type=order.order_type, delivery_fee=order.delivery_fee, 
                    offer_code=None, customer_phone=order.customer_phone, cashier_id=current_user_id
                )
                pricing_res = await self.pricing_service.calculate_price(pricing_req)
                
                if pricing_res.discount_amount < Decimal("0.00") or pricing_res.discount_amount > pricing_res.subtotal or pricing_res.total_amount < Decimal("0.00"):
                    raise ValidationError("Invalid financial state after recalculating.")
                
                if update_data.items is not None:
                    order.items = []
                    for item_data in update_data.items:
                        item = models.OrderItem(**item_data.model_dump())
                        item.total_price = item.quantity * item.unit_price
                        order.items.append(item)
                
                order.subtotal = pricing_res.subtotal
                order.discount_amount = pricing_res.discount_amount
                order.delivery_fee = pricing_res.delivery_fee
                order.total_amount = pricing_res.total_amount

            updated_order = await self.repository.update_order_full(order, update_data, changed_by_user_id=current_user_id)
        
        completed_order = await self.get_order(updated_order.id)
        completed_schema = schemas.OrderResponse.model_validate(completed_order)
        payload_data = completed_schema.model_dump(mode='json')
        self._record_outbox_event("ORDER_UPDATED", payload_data)
        from app.core.events import outbox_sync_trigger
        outbox_sync_trigger.set()
        order_events_manager.emit({
            "type": "ORDER_UPDATED",
            "event": "order.updated",
            "data": payload_data
        })
        return completed_order

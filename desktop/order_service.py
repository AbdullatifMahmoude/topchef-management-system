from typing import Any, Dict, List, Optional
from desktop.local_repository import local_repository
from desktop.pricing_service import pricing_service
from desktop.customer_service import customer_service
from desktop.sync_engine import sync_engine
from desktop.ws_relay import local_ws_manager
from desktop.logger import desktop_logger as log

class OrderService:
    async def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates an order locally, following the cloud service flow:
        1. Link/Create customer
        2. Calculate pricing
        3. Persist to local DB
        4. Trigger sync and broadcast
        """
        # 1. Automatic Customer Linking
        phone = order_data.get("customer_phone")
        name = order_data.get("customer_name")
        if phone and name:
            cust = customer_service.get_or_create_customer(phone, name)
            order_data["customer_id"] = cust.get("id")
            
            # Handle address if provided
            address = order_data.get("customer_address")
            if address and cust.get("id"):
                customer_service.add_address(cust["id"], address)

        # 2. Pricing Calculation
        pricing = pricing_service.calculate_price(
            items=order_data.get("items", []),
            order_type=order_data.get("order_type", "hall"),
            delivery_fee=order_data.get("delivery_fee", 0),
            offer_code=order_data.get("offer_code")
        )
        
        # Enrich order data with calculated financials
        order_data["subtotal"] = pricing["subtotal"]
        order_data["discount_amount"] = pricing["discount_amount"]
        order_data["total_amount"] = pricing["total_amount"]
        
        # 3. Persistence
        if not order_data.get("order_number"):
            order_data["order_number"] = local_repository.next_order_number()
            
        order = local_repository.create_order(order_data)
        
        # 4. Notifications & Sync
        sync_engine.trigger_full_sync(reason="order-created", wait=False)
        
        await local_ws_manager.broadcast({
            "event": "order.created",
            "data": order
        })
        
        return order

    async def update_order_status(self, order_id: int, status: str) -> Dict[str, Any]:
        """Update order status and broadcast change."""
        order = local_repository.update_order_status(order_id, status)
        
        sync_engine.trigger_full_sync(reason="order-status-updated", wait=False)
        
        await local_ws_manager.broadcast({
            "event": "order.updated",
            "data": order
        })
        
        return order

    async def update_order(self, order_id: int, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update order with comprehensive fields.
        Matches the logic in the cloud OrderService.
        """
        order = local_repository.get_order(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
            
        # 1. Customer updates
        phone = update_data.get("customer_phone") or order.get("customer_phone")
        name = update_data.get("customer_name") or order.get("customer_name")
        if phone and name:
            cust = customer_service.get_or_create_customer(phone, name)
            update_data["customer_id"] = cust.get("id")
            
            address = update_data.get("customer_address")
            if address and cust.get("id"):
                customer_service.add_address(cust["id"], address)

        # 2. Pricing updates
        needs_reprice = False
        items = update_data.get("items")
        delivery_fee = update_data.get("delivery_fee")
        
        if items is not None or (delivery_fee is not None and delivery_fee != order.get("delivery_fee")):
            needs_reprice = True
            
        if needs_reprice:
            calc_items = items if items is not None else order.get("items", [])
            calc_fee = delivery_fee if delivery_fee is not None else order.get("delivery_fee", 0)
            
            pricing = pricing_service.calculate_price(
                items=calc_items,
                order_type=order.get("order_type", "hall"),
                delivery_fee=calc_fee,
                offer_code=None # Reset offers on update for simplicity
            )
            update_data["subtotal"] = pricing["subtotal"]
            update_data["discount_amount"] = pricing["discount_amount"]
            update_data["total_amount"] = pricing["total_amount"]

        # 3. Persistence
        updated_order = local_repository.update_order_full(order_id, update_data)
        
        # 4. Notifications & Sync
        sync_engine.trigger_full_sync(reason="order-updated", wait=False)
        
        await local_ws_manager.broadcast({
            "event": "order.updated",
            "data": updated_order
        })
        
        return updated_order

    def get_order(self, order_id: int) -> Dict[str, Any]:
        return local_repository.get_order(order_id)

    def list_orders(self, **kwargs) -> Dict[str, Any]:
        return local_repository.list_orders(**kwargs)

order_service = OrderService()

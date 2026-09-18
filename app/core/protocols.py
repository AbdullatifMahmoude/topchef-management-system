from typing import Protocol, Optional, List, Any
from decimal import Decimal

class CacheStore(Protocol):
    async def get(self, key: str) -> Optional[str]: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str) -> int: ...
    async def decr(self, key: str) -> int: ...

class PricingServiceInterface(Protocol):
    async def calculate_price(self, request: Any) -> Any: ...

class OfferServiceInterface(Protocol):
    async def apply_offer(
        self, 
        code: str, 
        subtotal: Decimal, 
        items: Optional[List] = None, 
        customer_phone: Optional[str] = None, 
        cashier_id: Optional[int] = None,
        commit_usage: bool = False, 
        order_id: Optional[int] = None,
        existing_order_id: Optional[int] = None,
    ) -> Any: ...

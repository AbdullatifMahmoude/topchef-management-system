from decimal import Decimal
from typing import Any, Protocol


class CacheStore(Protocol):
    async def get(self, key: str) -> str | None: ...
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
        items: list | None = None,
        customer_phone: str | None = None,
        cashier_id: int | None = None,
        commit_usage: bool = False, 
        order_id: int | None = None,
        existing_order_id: int | None = None,
    ) -> Any: ...

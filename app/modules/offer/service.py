import json
from datetime import datetime
import contextlib
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.offer.repository import OfferRepository
from app.modules.offer.schemas import OfferCreate, OfferUpdate, OfferResponse, ApplyOfferResponse
from typing import List, Optional
from decimal import Decimal
from app.core.enums import DiscountType
from app.core.logging import logger

class OfferService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repository = OfferRepository(db)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def _invalidate_cache(self, offer=None):
        if self.redis:
            try:
                # 1. Update version instead of deleting (prevents thundering herd)
                await self.redis.incr("offers:version")
                # 2. Invalidate specific offer entries if provided
                if offer:
                    await self.redis.delete(f"offer:code:{offer.code}")
                    await self.redis.delete(f"offer:id:{offer.offer_id}")
            except Exception as e:
                logger.warning(f"Redis error invalidating offers cache: {e}")

    async def _get_cached_offer(self, key_prefix: str, identifier: str) -> Optional[OfferResponse]:
        if not self.redis:
            return None
        try:
            cache_key = f"offer:{key_prefix}:{identifier}"
            cached = await self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                offer = OfferResponse(**data)
                # TTL check against logical expiration
                if offer.is_active and offer.valid_to < datetime.utcnow():
                    return None
                return offer
        except Exception as e:
            logger.warning(f"Redis error reading granular offer cache {identifier}: {e}")
        return None

    async def _cache_offer(self, offer_res: OfferResponse):
        if not self.redis:
            return
        try:
            data = json.dumps(offer_res.model_dump(mode='json'))
            await self.redis.setex(f"offer:code:{offer_res.code}", 3600, data)
            await self.redis.setex(f"offer:id:{offer_res.offer_id}", 3600, data)
        except Exception as e:
            logger.warning(f"Redis error caching offer {offer_res.code}: {e}")

    async def create_offer(self, offer_data: OfferCreate) -> OfferResponse:
        async with self._transaction_scope():
            existing_offer = await self.repository.get_by_code(offer_data.code)
            if existing_offer:
                raise ValidationError(f"Offer with code '{offer_data.code}' already exists")
            
            offer = await self.repository.create(offer_data)
            await self.db.flush()
            logger.info(f"Offer created: code='{offer.code}', type='{offer.discount_type}'")
            await self._invalidate_cache(offer)
        
        return OfferResponse.model_validate(offer)

    async def list_all_offers(self, only_active: bool = False) -> List[OfferResponse]:
        # 1. Get current cache version
        version = "1"
        if self.redis:
            try:
                version = await self.redis.get("offers:version") or "1"
            except Exception:
                pass
        
        # Distinguish cache by active status
        cache_key = f"offers:{'active' if only_active else 'all'}:v{version}"
        
        # 2. Try Cache
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return [OfferResponse(**item) for item in data]
            except Exception as e:
                logger.warning(f"Redis error reading offers: {e}")

        # 3. DB Fallback
        async with self._transaction_scope():
            offers = await self.repository.list_offers(only_active=only_active)
            
            # Auto-maintenance: deactivate if needed (only for full list or if we want latest status)
            if not only_active:
                for offer in offers:
                    offer.deactivate_if_expired()
                    offer.deactivate_if_usage_full()
                await self.db.flush()
            
            response = [OfferResponse.model_validate(offer) for offer in offers]

            # 4. Save to Cache (5 minutes)
            if self.redis:
                try:
                    serializable = [o.model_dump(mode='json') for o in response]
                    await self.redis.setex(cache_key, 300, json.dumps(serializable))
                except Exception as e:
                    logger.warning(f"Redis error writing offers cache: {e}")
        
        return response

    async def get_offer_by_id(self, offer_id: int, check_cache: bool = True) -> OfferResponse:
        # 1. Granular Cache Path
        if check_cache and self.redis:
            cached = await self._get_cached_offer("id", str(offer_id))
            if cached:
                return cached

        # 2. Database Path
        async with self._transaction_scope():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            deactivated_exp = offer.deactivate_if_expired()
            deactivated_usage = offer.deactivate_if_usage_full()
            
            if deactivated_exp or deactivated_usage:
                logger.info(f"Offer code '{offer.code}' deactivated automatically on access.")
                await self.db.flush()
                await self._invalidate_cache(offer)
            
            response = OfferResponse.model_validate(offer)
            if check_cache:
                await self._cache_offer(response)
            return response

    async def get_offer_by_code(self, code: str, check_cache: bool = True) -> OfferResponse:
        # 1. Granular Cache Path
        if check_cache and self.redis:
            cached = await self._get_cached_offer("code", code)
            if cached:
                return cached

        # 2. Database Path
        async with self._transaction_scope():
            offer = await self.repository.get_by_code(code)
            if not offer:
                raise NotFoundError(f"Offer code '{code}'")
            
            deactivated_exp = offer.deactivate_if_expired()
            deactivated_usage = offer.deactivate_if_usage_full()
            
            if deactivated_exp or deactivated_usage:
                 logger.info(f"Offer code '{offer.code}' deactivated automatically on access.")
                 await self.db.flush()
                 await self._invalidate_cache(offer)
            
            response = OfferResponse.model_validate(offer)
            if check_cache:
                await self._cache_offer(response)
            return response

    async def update_offer(self, offer_id: int, offer_data: OfferUpdate) -> OfferResponse:
        async with self._transaction_scope():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            # Map update data via model's rich method
            update_dict = offer_data.model_dump(exclude_unset=True)
            for key in ["valid_from", "valid_to"]:
                if isinstance(update_dict.get(key), datetime):
                    update_dict[key] = update_dict[key].replace(tzinfo=None)
            
            offer.update_info(update_dict)
            
            await self.db.flush()
            logger.info(f"Offer updated: id={offer_id}, code='{offer.code}'")
            await self._invalidate_cache(offer)
        
        return OfferResponse.model_validate(offer)

    async def delete_offer(self, offer_id: int) -> bool:
        async with self._transaction_scope():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            await self.repository.delete(offer)
            logger.info(f"Offer deleted: id={offer_id}")
            await self._invalidate_cache(offer)
        return True

    async def apply_offer(self, code: str, subtotal: Decimal, items: List = None, 
                          customer_phone: str = None, cashier_id: int = None,
                          commit_usage: bool = False, order_id: int = None) -> ApplyOfferResponse:
        """
        Production-ready offer application logic:
        - Validates timing (start/end) and status.
        - Enforces global and per-customer limits with row-level locking (SELECT FOR UPDATE).
        - Atomic usage incrementing if commit_usage=True.
        - Detailed BOGO, Percentage, and Fixed math with precision.
        """
        async with self._transaction_scope():
            # 1. Fetch the offer with row-level locking to prevent race conditions
            offer = await self.repository.get_by_code(code, lock=True)
            if not offer:
                logger.warning(f"ApplyOffer failure: Invalid code '{code}'")
                raise ValidationError(f"Invalid offer code: {code}")
            
            # --- 1. Timing & Status ---
            if commit_usage:
                offer.deactivate_if_expired()
                offer.deactivate_if_usage_full()
            else:
                if offer.is_expired() or offer.is_usage_limit_reached():
                    raise ValidationError("Offer is no longer active or has expired")
            
            if not offer.is_active:
                raise ValidationError("Offer is no longer active or has expired")
            
            if not offer.is_started():
                startTime = offer.valid_from.strftime('%Y-%m-%d %H:%M')
                raise ValidationError(f"Offer is not yet valid. Starts at {startTime}")

            # --- 2. Global Usage Check ---
            if offer.is_usage_limit_reached():
                if commit_usage:
                    offer.is_active = False # Safe-guard deactivation
                raise ValidationError("Offer global usage limit reached")
            
            # --- 3. Per-Customer Usage Check (Redis-Optimized) ---
            if offer.usage_per_user:
                if self.redis and customer_phone:
                    user_usage_key = f"offer:usage:user:{offer.code}:{customer_phone}"
                    try:
                        current_u = await self.redis.get(user_usage_key)
                        if current_u and int(current_u) >= offer.usage_per_user:
                            raise ValidationError(f"Limit reached. You have already used this offer {current_u} times.")
                    except (ValueError, TypeError):
                        pass

                identity_count = await self.repository.get_customer_usage_count(
                    offer.offer_id, customer_phone=customer_phone, cashier_id=cashier_id
                )
                if identity_count >= offer.usage_per_user:
                    # Sync Redis if it was missing
                    if self.redis and customer_phone:
                        await self.redis.setex(f"offer:usage:user:{offer.code}:{customer_phone}", 86400, identity_count)
                    raise ValidationError(f"You have already used this offer {identity_count} times.")

            # --- 4. Content Thresholds ---
            # A) Basket Value
            if offer.min_order_amount and subtotal < Decimal(str(offer.min_order_amount)):
                raise ValidationError(
                    f"Order must be at least {offer.min_order_amount} to use this offer."
                )
            
            # B) Basket Quantity
            total_qty = sum(item.quantity for item in items) if items else 0
            if offer.min_quantity and total_qty < offer.min_quantity:
                raise ValidationError(f"Requires at least {offer.min_quantity} items.")
            if offer.max_quantity and total_qty > offer.max_quantity:
                # Note: We reject here for simplicity, though capping is an alternative
                raise ValidationError(f"Offer limited to {offer.max_quantity} items per order.")

            # --- 5. Calculation Logic ---
            calculated_discount = Decimal("0.00")
            dtype = offer.discount_type
            dval = Decimal(str(offer.discount_value))

            if dtype == DiscountType.PERCENTAGE:
                calculated_discount = subtotal * (dval / Decimal("100.0"))
            
            elif dtype == DiscountType.FIXED:
                calculated_discount = dval
            
            elif dtype == DiscountType.BUY_ONE_GET_ONE:
                if items:
                    sorted_items = sorted(items, key=lambda x: x.unit_price)
                    total_quantity = sum(item.quantity for item in sorted_items)
                    free_units = total_quantity // 2
                    for item in sorted_items:
                        if free_units <= 0:
                            break
                        units_to_discount = min(item.quantity, free_units)
                        calculated_discount += Decimal(str(units_to_discount)) * Decimal(str(item.unit_price))
                        free_units -= units_to_discount
                else:
                    logger.warning(f"BOGO offer '{code}' applied to empty basket context.")
            
            # --- 6. Caps and Safeties ---
            if offer.max_discount_amount:
                max_bound = Decimal(str(offer.max_discount_amount))
                calculated_discount = min(calculated_discount, max_bound)
            
            # Absolute Floor: Can't discount more than the subtotal
            discount_amount = min(calculated_discount, subtotal).quantize(Decimal("0.00"))
            
            # --- 7. Usage Tracking (Atomic Redis + DB) ---
            if commit_usage:
                # A) Redis Global Check/Update
                if self.redis and offer.usage_limit:
                    global_key = f"offer:usage:global:{offer.code}"
                    new_val = await self.redis.incr(global_key)
                    if new_val > offer.usage_limit:
                        await self.redis.decr(global_key)
                        raise ValidationError("Offer global usage limit reached (Redis Guard)")
                
                # B) Redis User Check/Update
                if self.redis and offer.usage_per_user and customer_phone:
                    user_key = f"offer:usage:user:{offer.code}:{customer_phone}"
                    new_u_val = await self.redis.incr(user_key)
                    if new_u_val > offer.usage_per_user:
                        await self.redis.decr(user_key)
                        raise ValidationError("Your personal limit for this offer has been reached.")

                # C) DB Update
                offer.current_usage += 1
                await self.repository.record_usage({
                    "offer_id": offer.offer_id,
                    "customer_phone": customer_phone,
                    "cashier_id": cashier_id,
                    "discount_amount": discount_amount,
                    "order_id": order_id
                })
                logger.info(f"Offer '{code}' REDEEMED (id:{offer.offer_id}) for phone:{customer_phone}")
                
                # Invalidating to sync current_usage in cache
                await self._invalidate_cache(offer)
            else:
                logger.info(f"Offer '{code}' VALIDATED (id:{offer.offer_id}) preview discount: {discount_amount}")

            return ApplyOfferResponse(
                items=items or [],
                subtotal=subtotal,
                discount_amount=discount_amount,
                total_after_discount=subtotal - discount_amount,
                offer_metadata=OfferResponse.model_validate(offer),
                applied_successfully=True,
                message="Offer applied successfully"
            )

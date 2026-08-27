import json
from datetime import datetime, timedelta, timezone
import contextlib
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.offer.repository import OfferRepository
from app.modules.offer.schemas import OfferCreate, OfferUpdate, OfferResponse, ApplyOfferResponse, OfferAnalyticsResponse, OfferUsageActivity
from typing import List, Optional
from decimal import Decimal, ROUND_HALF_UP
from app.core.enums import DiscountType
from app.core.logging import logger
from sqlalchemy import select
from app.modules.customer.phone import normalize_egyptian_phone


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

    async def _emit_offer_change(self, action: str, offer_id: int) -> None:
        try:
            from app.core.events import order_events_manager
            await order_events_manager.emit({
                "type": "OFFER_UPDATED",
                "data": {"id": offer_id, "action": action},
            })
        except Exception as exc:
            # The database change remains valid if a client is temporarily
            # offline; clients also refresh on reconnect/visibility change.
            logger.warning(f"Could not broadcast offer update {offer_id}: {exc}")

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
                cairo_now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
                if offer.is_active and offer.valid_to < cairo_now:
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

    async def _resolve_products(self, product_ids: List[int]):
        if not product_ids:
            return []
        from app.modules.menu.models import Product
        unique_ids = list(dict.fromkeys(product_ids))
        products = list((await self.db.execute(select(Product).where(
            Product.id.in_(unique_ids),
            Product.is_deleted == False,
            Product.is_available == True,
        ))).scalars().all())
        if len(products) != len(unique_ids):
            raise ValidationError("بعض الأصناف المختارة غير موجودة أو موقوفة")
        return products

    @staticmethod
    def _validate_configuration(offer) -> None:
        if offer.valid_to <= offer.valid_from:
            raise ValidationError("تاريخ نهاية العرض يجب أن يكون بعد تاريخ البداية")
        if offer.min_quantity and offer.max_quantity and offer.min_quantity > offer.max_quantity:
            raise ValidationError("الحد الأدنى للكمية لا يمكن أن يتجاوز الحد الأقصى")
        if offer.discount_type in (DiscountType.PERCENTAGE, DiscountType.QUANTITY_DISCOUNT, DiscountType.HAPPY_HOUR) and Decimal(str(offer.discount_value)) > 100:
            raise ValidationError("نسبة الخصم لا يمكن أن تتجاوز 100%")
        if offer.usage_limit and int(offer.current_usage or 0) > offer.usage_limit:
            raise ValidationError("حد الاستخدام الجديد أقل من عدد مرات الاستخدام الحالية")
        rules = offer.rules or {}
        dtype = offer.discount_type
        if dtype == DiscountType.COMBO:
            if not rules.get("requirements") or Decimal(str(rules.get("combo_price", 0))) <= 0:
                raise ValidationError("عرض الكومبو يحتاج أصنافًا وسعر كومبو صحيحًا")
        elif dtype == DiscountType.BUY_X_GET_Y:
            if not rules.get("buy_product_ids") or not rules.get("get_product_ids"):
                raise ValidationError("حدد أصناف الشراء وأصناف الهدية")
            if int(rules.get("buy_quantity", 0)) <= 0 or int(rules.get("get_quantity", 0)) <= 0:
                raise ValidationError("كميات اشترِ X وخذ Y يجب أن تكون أكبر من صفر")
            reward_percent = Decimal(str(rules.get("reward_percent", 100)))
            if reward_percent <= 0 or reward_percent > 100:
                raise ValidationError("نسبة خصم الهدية يجب أن تكون بين 1% و100%")
        elif dtype == DiscountType.QUANTITY_DISCOUNT:
            if int(rules.get("quantity_required", 0)) <= 0:
                raise ValidationError("حدد الكمية المطلوبة لتفعيل الخصم")
        elif dtype == DiscountType.CATEGORY_DISCOUNT:
            if not rules.get("category_ids"):
                raise ValidationError("اختر تصنيفًا واحدًا على الأقل")
            if rules.get("discount_mode", "percentage") == "percentage" and Decimal(str(offer.discount_value)) > 100:
                raise ValidationError("نسبة الخصم لا يمكن أن تتجاوز 100%")
        elif dtype == DiscountType.HAPPY_HOUR:
            if not rules.get("start_time") or not rules.get("end_time"):
                raise ValidationError("حدد وقت بداية ونهاية العرض")

    async def create_offer(self, offer_data: OfferCreate) -> OfferResponse:
        async with self._transaction_scope():
            offer_data.code = offer_data.code.strip().upper()
            existing_offer = await self.repository.get_by_code(offer_data.code)
            if existing_offer:
                raise ValidationError(f"Offer with code '{offer_data.code}' already exists")
            
            offer = await self.repository.create(offer_data)
            offer.products = await self._resolve_products(offer_data.product_ids)
            self._validate_configuration(offer)
            await self.db.flush()
            logger.info(f"Offer created: code='{offer.code}', type='{offer.discount_type}'")
            await self._invalidate_cache(offer)
        
        # Persist before notifying live clients so their immediate refresh can
        # never read the previous version of the offer.
        if self.db.in_transaction():
            await self.db.commit()
        await self._invalidate_cache(offer)
        response = OfferResponse.model_validate(offer)
        await self._emit_offer_change("created", offer.offer_id)
        return response

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

    async def get_analytics(self) -> OfferAnalyticsResponse:
        egypt_tz = timezone(timedelta(hours=3))
        local_now = datetime.now(egypt_tz)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = (start_local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        offers = await self.repository.list_offers(only_active=False)
        now = datetime.now(egypt_tz).replace(tzinfo=None)
        active_now = sum(1 for offer in offers if offer.is_active and offer.valid_from <= now <= offer.valid_to and not offer.is_usage_limit_reached())
        scheduled = sum(1 for offer in offers if offer.is_active and offer.valid_from > now)
        stopped_or_ended = len(offers) - active_now - scheduled
        redemptions, total_discount, rows = await self.repository.usage_analytics(start_utc, end_utc)
        activity = [OfferUsageActivity(
            offer_name=display_name or code,
            offer_code=code,
            customer_phone=usage.customer_phone,
            cashier_name=full_name,
            order_id=usage.order_id,
            discount_amount=usage.discount_amount,
            applied_at=usage.applied_at,
        ) for usage, display_name, code, full_name in rows]
        return OfferAnalyticsResponse(
            active_now=active_now, scheduled=scheduled, stopped_or_ended=stopped_or_ended,
            redemptions_today=redemptions, discounts_today=total_discount,
            recent_activity=activity,
        )

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
            product_ids = update_dict.pop("product_ids", None)
            if update_dict.get("code"):
                update_dict["code"] = update_dict["code"].strip().upper()
                duplicate = await self.repository.get_by_code(update_dict["code"])
                if duplicate and duplicate.offer_id != offer_id:
                    raise ValidationError(f"Offer with code '{update_dict['code']}' already exists")
            for key in ["valid_from", "valid_to"]:
                if isinstance(update_dict.get(key), datetime):
                    update_dict[key] = update_dict[key].replace(tzinfo=None)
            
            offer.update_info(update_dict)
            if product_ids is not None:
                offer.products = await self._resolve_products(product_ids)
            self._validate_configuration(offer)
            
            await self.db.flush()
            logger.info(f"Offer updated: id={offer_id}, code='{offer.code}'")
            await self._invalidate_cache(offer)
        
        if self.db.in_transaction():
            await self.db.commit()
        await self._invalidate_cache(offer)
        response = OfferResponse.model_validate(offer)
        await self._emit_offer_change("updated", offer.offer_id)
        return response

    async def delete_offer(self, offer_id: int) -> bool:
        async with self._transaction_scope():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            await self.repository.delete(offer)
            logger.info(f"Offer deleted: id={offer_id}")
            await self._invalidate_cache(offer)
            deleted_id = offer.offer_id
        if self.db.in_transaction():
            await self.db.commit()
        await self._invalidate_cache(offer)
        await self._emit_offer_change("deleted", deleted_id)
        return True

    async def apply_offer(self, code: str, subtotal: Decimal, items: List = None, 
                          customer_phone: str = None, cashier_id: int = None,
                          commit_usage: bool = False, order_id: int = None,
                          existing_order_id: int = None) -> ApplyOfferResponse:
        """
        Production-ready offer application logic:
        - Validates timing (start/end) and status.
        - Enforces global and per-customer limits with row-level locking (SELECT FOR UPDATE).
        - Atomic usage incrementing if commit_usage=True.
        - Detailed BOGO, Percentage, and Fixed math with precision.
        """
        async with self._transaction_scope():
            # 1. Fetch the offer with row-level locking to prevent race conditions
            code = code.strip().upper()
            customer_phone = normalize_egyptian_phone(customer_phone)
            offer = await self.repository.get_by_code(code, lock=True)
            if not offer:
                logger.warning(f"ApplyOffer failure: Invalid code '{code}'")
                raise ValidationError(f"Invalid offer code: {code}")

            existing_redemption = False
            if existing_order_id:
                from app.modules.offer.models import OfferUsage
                existing_redemption = bool(await self.db.scalar(select(OfferUsage.usage_id).where(
                    OfferUsage.offer_id == offer.offer_id,
                    OfferUsage.order_id == existing_order_id,
                )))
            
            # --- 1. Timing & Status ---
            if existing_redemption:
                pass
            elif commit_usage:
                offer.deactivate_if_expired()
                offer.deactivate_if_usage_full()
            else:
                if offer.is_expired() or offer.is_usage_limit_reached():
                    raise ValidationError("Offer is no longer active or has expired")
            
            if not existing_redemption and not offer.is_active:
                raise ValidationError("Offer is no longer active or has expired")
            
            if not existing_redemption and not offer.is_started():
                startTime = offer.valid_from.strftime('%Y-%m-%d %H:%M')
                raise ValidationError(f"Offer is not yet valid. Starts at {startTime}")

            # --- 2. Global Usage Check ---
            if not existing_redemption and offer.is_usage_limit_reached():
                if commit_usage:
                    offer.is_active = False # Safe-guard deactivation
                raise ValidationError("Offer global usage limit reached")
            
            # --- 3. Per-Customer Usage Check ---
            # A personal limit is meaningful only with a stable customer
            # identity, regardless of whether the order is online or cashier.
            has_customer_identity = bool(customer_phone and len(customer_phone) == 11)
            if not existing_redemption and offer.usage_per_user and not has_customer_identity:
                raise ValidationError("يجب إدخال رقم هاتف العميل الصحيح لاستخدام هذا العرض")
            enforce_customer_limit = bool(not existing_redemption and offer.usage_per_user and has_customer_identity)
            if enforce_customer_limit:
                identity_count = await self.repository.get_customer_usage_count(
                    offer.offer_id, customer_phone=customer_phone
                )
                if identity_count >= offer.usage_per_user:
                    raise ValidationError("هذا العميل استنفد عدد مرات استخدام العرض")

            # --- 4. Eligible products and thresholds ---
            rules = offer.rules or {}
            selected_product_ids = {product.id for product in offer.products}
            category_ids = {int(value) for value in rules.get("category_ids", [])}
            has_product_scope = bool(selected_product_ids or category_ids)
            if category_ids:
                from app.modules.menu.models import Product
                category_product_ids = set((await self.db.execute(
                    select(Product.id).where(Product.cat_id.in_(category_ids), Product.is_available == True)
                )).scalars().all())
                selected_product_ids.update(category_product_ids)
            eligible_items = [item for item in (items or []) if not has_product_scope or item.product_id in selected_product_ids]
            eligible_subtotal = sum(
                (Decimal(str(item.unit_price)) * item.quantity for item in eligible_items),
                Decimal("0.00"),
            )
            if has_product_scope and not eligible_items:
                raise ValidationError("العرض لا ينطبق على أي صنف موجود في الطلب")

            # A) Basket Value
            if offer.min_order_amount and eligible_subtotal < Decimal(str(offer.min_order_amount)):
                raise ValidationError(
                    f"Order must be at least {offer.min_order_amount} to use this offer."
                )
            
            # B) Basket Quantity
            total_qty = sum(item.quantity for item in eligible_items)
            if offer.min_quantity and total_qty < offer.min_quantity:
                raise ValidationError(f"Requires at least {offer.min_quantity} items.")
            if offer.max_quantity and total_qty > offer.max_quantity:
                # Note: We reject here for simplicity, though capping is an alternative
                raise ValidationError(f"Offer limited to {offer.max_quantity} items per order.")

            # --- 5. Calculation Logic ---
            calculated_discount = Decimal("0.00")
            dtype = offer.discount_type
            dval = Decimal(str(offer.discount_value))
            waive_delivery_fee = False

            if dtype == DiscountType.PERCENTAGE:
                calculated_discount = eligible_subtotal * (dval / Decimal("100.0"))
            
            elif dtype == DiscountType.FIXED:
                calculated_discount = min(dval, eligible_subtotal)
            
            elif dtype == DiscountType.BUY_ONE_GET_ONE:
                if eligible_items:
                    sorted_items = sorted(eligible_items, key=lambda x: x.unit_price)
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

            elif dtype == DiscountType.COMBO:
                requirements = rules.get("requirements", [])
                item_quantities = {}
                item_prices = {}
                for item in items or []:
                    pid = int(item.product_id)
                    item_quantities[pid] = item_quantities.get(pid, 0) + int(item.quantity)
                    price = Decimal(str(item.unit_price))
                    item_prices[pid] = min(item_prices.get(pid, price), price)
                bundle_counts = []
                regular_bundle_price = Decimal("0.00")
                for requirement in requirements:
                    pid = int(requirement["product_id"])
                    qty = max(1, int(requirement.get("quantity", 1)))
                    bundle_counts.append(item_quantities.get(pid, 0) // qty)
                    regular_bundle_price += item_prices.get(pid, Decimal("0.00")) * qty
                bundles = min(bundle_counts) if bundle_counts else 0
                if bundles < 1:
                    raise ValidationError("أضف كل أصناف الكومبو بالكميات المطلوبة")
                combo_price = Decimal(str(rules.get("combo_price")))
                calculated_discount = max(Decimal("0.00"), regular_bundle_price - combo_price) * bundles

            elif dtype == DiscountType.BUY_X_GET_Y:
                buy_ids = {int(value) for value in rules.get("buy_product_ids", [])}
                get_ids = {int(value) for value in rules.get("get_product_ids", [])}
                buy_qty = max(1, int(rules.get("buy_quantity", 1)))
                get_qty = max(1, int(rules.get("get_quantity", 1)))
                bought = sum(int(item.quantity) for item in (items or []) if int(item.product_id) in buy_ids)
                reward_units = (bought // buy_qty) * get_qty
                reward_items = sorted(
                    (item for item in (items or []) if int(item.product_id) in get_ids),
                    key=lambda item: Decimal(str(item.unit_price)),
                )
                available_rewards = sum(int(item.quantity) for item in reward_items)
                if reward_units < 1 or available_rewards < 1:
                    raise ValidationError("شروط اشترِ X وخذ Y غير مكتملة في الطلب")
                reward_units = min(reward_units, available_rewards)
                reward_percent = Decimal(str(rules.get("reward_percent", 100))) / Decimal("100")
                for item in reward_items:
                    units = min(int(item.quantity), reward_units)
                    calculated_discount += Decimal(str(item.unit_price)) * units * reward_percent
                    reward_units -= units
                    if reward_units <= 0:
                        break

            elif dtype == DiscountType.QUANTITY_DISCOUNT:
                required = max(1, int(rules.get("quantity_required", 1)))
                if total_qty < required:
                    raise ValidationError(f"العرض يحتاج شراء {required} وحدات على الأقل")
                calculated_discount = eligible_subtotal * (dval / Decimal("100"))

            elif dtype == DiscountType.FREE_DELIVERY:
                waive_delivery_fee = True

            elif dtype == DiscountType.CATEGORY_DISCOUNT:
                mode = rules.get("discount_mode", "percentage")
                calculated_discount = (
                    eligible_subtotal * (dval / Decimal("100"))
                    if mode == "percentage" else min(dval, eligible_subtotal)
                )

            elif dtype == DiscountType.HAPPY_HOUR:
                from datetime import time
                def parse_offer_time(value):
                    hours, minutes = str(value).split(":")[:2]
                    return time(int(hours), int(minutes))
                # Happy-hour windows follow the normal wall clock; they are not
                # shifted by the restaurant's business-day/shift cutoff.
                cairo_tz = timezone(timedelta(hours=3))
                now_time = datetime.now(cairo_tz).time().replace(second=0, microsecond=0, tzinfo=None)
                start_time = parse_offer_time(rules["start_time"])
                end_time = parse_offer_time(rules["end_time"])
                in_window = start_time <= now_time <= end_time if start_time <= end_time else (now_time >= start_time or now_time <= end_time)
                if not in_window:
                    raise ValidationError("العرض غير متاح في الساعة الحالية")
                calculated_discount = eligible_subtotal * (dval / Decimal("100"))
            
            # --- 6. Caps and Safeties ---
            if offer.max_discount_amount:
                max_bound = Decimal(str(offer.max_discount_amount))
                calculated_discount = min(calculated_discount, max_bound)
            
            # Absolute Floor: Can't discount more than the subtotal
            discount_amount = min(calculated_discount, eligible_subtotal, subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            # --- 7. Atomic usage tracking ---
            if commit_usage:
                # The locked database row is the single source of truth. Redis
                # is deliberately not used as a counter here: incrementing it
                # before a later DB rollback can reject valid customers.
                offer.current_usage = int(offer.current_usage or 0) + 1
                await self.repository.record_usage({
                    "offer_id": offer.offer_id,
                    "customer_phone": customer_phone if has_customer_identity else None,
                    "cashier_id": cashier_id,
                    "discount_amount": discount_amount,
                    "order_id": order_id
                })
                logger.info("Offer redeemed code=%s id=%s", code, offer.offer_id)
                
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
                ,waive_delivery_fee=waive_delivery_fee
            )

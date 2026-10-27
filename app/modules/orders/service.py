import contextlib
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_calendar import get_current_business_date, is_weekly_holiday
from app.core.enums import OrderSource, OrderStatus, OrderType, PaymentMethod, UserRole
from app.core.events import order_events_manager
from app.core.exceptions import NotFoundError, ValidationError
from app.core.protocols import (
    CacheStore,
    OfferServiceInterface,
    PricingServiceInterface,
)
from app.modules.customer.loyalty import (
    award_order_points,
    recalculate_order_points,
    reverse_order_points,
    select_redemption,
)
from app.modules.offer.service import OfferService
from app.modules.orders import models, schemas
from app.modules.orders.notifications import (
    AccountOrderNotifications,
    OrderNotificationPort,
)
from app.modules.orders.repository import OrderRepository
from app.modules.pricing.schemas import PricingItem, PricingRequest
from app.modules.pricing.service import PricingService
from app.modules.settings.service import SettingsService


class OrderService:
    def __init__(
        self, 
        db: AsyncSession, 
        redis: CacheStore | None = None,
        pricing_service: PricingServiceInterface | None = None,
        offer_service: OfferServiceInterface | None = None,
        notification_service: OrderNotificationPort | None = None,
    ):
        self.db = db
        self.repository = OrderRepository(db)
        self.redis = redis
        self.pricing_service = pricing_service or PricingService(db)
        self.offer_service = offer_service or OfferService(db, redis=redis)
        self.settings_service = SettingsService(db, redis=redis)
        self.notifications = notification_service or AccountOrderNotifications(db)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def _validate_order_items(self, items: list[schemas.OrderItemCreate]):
        """Validate products exist and are available."""
        from app.modules.menu.service import ProductService
        
        product_ids = [item.product_id for item in items]
        if not product_ids:
            raise ValidationError("أضف صنفًا واحدًا على الأقل قبل إرسال الطلب")
        
        menu_service = ProductService(self.db)
        products = await menu_service.get_products_by_ids(product_ids)
        products_by_id = {p.id: p for p in products}
        
        for item in items:
            if item.product_id not in products_by_id:
                raise ValidationError("أحد الأصناف لم يعد موجودًا. حدّث المنيو وحاول تاني")
            
            product = products_by_id[item.product_id]
            if not product.is_available:
                raise ValidationError(f"الصنف «{product.product_name}» غير متاح حاليًا")
            if getattr(product, "is_temporarily_unavailable", False):
                raise ValidationError(f"الصنف «{product.product_name}» غير متاح لباقي يوم العمل. احذفه من السلة وحاول تاني")
            if not product.category or not product.category.is_active or product.category.is_deleted:
                raise ValidationError(f"قسم الصنف «{product.product_name}» غير متاح حاليًا")

            requested_price = Decimal(str(item.unit_price)).quantize(Decimal("0.01"))
            allowed_prices = {
                Decimal(str(variant.price)).quantize(Decimal("0.01"))
                for variant in product.variants
                if not variant.is_deleted
            }
            if requested_price not in allowed_prices:
                raise ValidationError(f"سعر الصنف «{product.product_name}» اتغير. حدّث المنيو واختاره من جديد")

    async def create_order(self, order_data: schemas.OrderCreate, current_user_id: int | None = None,
                           redeeming_customer: dict | None = None) -> models.Order:
        import asyncio as _asyncio

        from sqlalchemy.exc import OperationalError as _OperationalError

        from app.core.logging import logger as _logger

        _max_retries = 3
        for _attempt in range(_max_retries):
            try:
                return await self._create_order_inner(order_data, current_user_id, redeeming_customer)
            except _OperationalError as exc:
                if "database is locked" in str(exc).lower() and _attempt < _max_retries - 1:
                    _logger.warning(
                        "Database locked during order creation (attempt %d/%d). Retrying in %.1fs...",
                        _attempt + 1, _max_retries, 0.5 * (_attempt + 1),
                    )
                    await _asyncio.sleep(0.5 * (_attempt + 1))
                else:
                    raise

    async def _create_order_inner(self, order_data: schemas.OrderCreate, current_user_id: int | None = None,
                                  redeeming_customer: dict | None = None) -> models.Order:
        # Linking a customer is server-owned state; never write it back into the caller's payload.
        order_data = order_data.model_copy(deep=True)
        async with self._transaction_scope():
            if is_weekly_holiday(get_current_business_date()):
                raise ValidationError("المطعم مغلق يوم الجمعة للإجازة الأسبوعية ولا يمكن إنشاء طلبات جديدة")

            # Check if online orders are enabled
            if order_data.source == models.OrderSource.ONLINE:
                if order_data.order_type == OrderType.PHONE_RESERVATION:
                    raise ValidationError("حجز التلفون متاح للكاشير فقط")
                if order_data.manual_discount_type or order_data.manual_discount_value:
                    raise ValidationError("الخصم اليدوي غير متاح لطلبات المنيو")
                if order_data.customer_id is not None:
                    raise ValidationError("بيانات الحساب يحددها النظام من بيانات العميل المسجل، ولا تقبل من الطلب مباشرة")
                checkout = await self.settings_service.get_menu_checkout_settings()
                if not checkout.ordering_enabled:
                    raise ValidationError(checkout.ordering_message)
                if order_data.payment_method == PaymentMethod.INSTAPAY and not checkout.instapay_enabled:
                    raise ValidationError("الدفع عن طريق InstaPay غير متاح حاليًا")
                if order_data.payment_method == PaymentMethod.WALLET and not checkout.wallet_enabled:
                    raise ValidationError("الدفع عن طريق المحفظة غير متاح حاليًا")

            if order_data.order_type == OrderType.PHONE_RESERVATION:
                from app.modules.customer.phone import normalize_egyptian_phone
                phone = normalize_egyptian_phone(order_data.customer_phone)
                if len(phone) != 11 or not phone.startswith("01"):
                    raise ValidationError("رقم تليفون العميل مطلوب لحجز التلفون ويجب أن يكون 11 رقمًا")
                order_data.customer_phone = phone

            # A cashier-created delivery is operational immediately, so it
            # must never enter the database without an active delivery rider.
            if order_data.order_type == OrderType.DELIVERY and order_data.source == OrderSource.CASHIER:
                if not order_data.delivery_person_id:
                    raise ValidationError("يجب اختيار مندوب قبل إنشاء طلب الدليفري")
                from app.modules.users.models import User
                rider = await self.db.get(User, order_data.delivery_person_id)
                if not rider or rider.role != UserRole.DELIVERY or not rider.is_active or rider.is_deleted:
                    raise ValidationError("المندوب المختار غير متاح")

            if order_data.loyalty_rule_id and (order_data.source != OrderSource.ONLINE or not redeeming_customer):
                raise ValidationError("استبدال النقاط متاح لصاحب الحساب من المنيو فقط")

            # Idempotency check
            if order_data.idempotency_key:
                existing = await self.repository.get_by_idempotency_key(order_data.idempotency_key)
                if existing:
                    if existing.customer_phone != order_data.customer_phone or existing.order_source != order_data.source \
                            or existing.loyalty_rule_id != (str(order_data.loyalty_rule_id) if order_data.loyalty_rule_id else None) \
                            or (order_data.loyalty_rule_id and existing.customer_id != redeeming_customer["customer_id"]):
                        raise ValidationError("مفتاح تكرار الطلب مستخدم لطلب مختلف")
                    return existing

            if order_data.source == OrderSource.CASHIER:
                from app.modules.shifts.cash_custody import active_shift
                from app.modules.users.models import User

                actor = await self.db.get(User, current_user_id) if current_user_id else None
                if not actor or actor.role not in (UserRole.CASHIER, UserRole.ADMIN):
                    raise ValidationError("إنشاء طلب الكاشير يتطلب حساب كاشير أو أدمن")
                if actor.role == UserRole.CASHIER:
                    await active_shift(self.db, actor.id)
            if order_data.digital_payment_verified:
                if not actor or actor.role != UserRole.CASHIER:
                    raise ValidationError("الكاشير فقط يؤكد وصول التحويل")
            elif order_data.source == OrderSource.CASHIER and order_data.payment_method in (PaymentMethod.INSTAPAY, PaymentMethod.WALLET):
                raise ValidationError("تأكد من وصول تحويل إنستا أو المحفظة قبل تسجيل الطلب")
            
            # Auto-create or link customer
            if order_data.customer_phone and order_data.customer_name:
                from app.modules.customer.schemas import (
                    CustomerAddressCreate,
                    CustomerCreate,
                )
                from app.modules.customer.service import CustomerService
                
                customer_service = CustomerService(self.db, self.redis)
                try:
                    existing_cust = await customer_service.get_customer_by_phone(order_data.customer_phone)
                    order_data.customer_id = existing_cust.id
                    # Update local customer name if different, and push sync event
                    if existing_cust.name != order_data.customer_name and order_data.customer_name:
                        existing_cust.name = order_data.customer_name
                        self.db.add(existing_cust)
                        
                        
                except NotFoundError:
                    # Phone not found — create new customer
                    try:
                        # Isolate the insert so a concurrent duplicate does not
                        # invalidate the transaction used to create the order.
                        async with self.db.begin_nested():
                            new_cust = await customer_service.create_customer(CustomerCreate(
                                name=order_data.customer_name,
                                phone_number=order_data.customer_phone,
                            ))
                        order_data.customer_id = new_cust.id
                    except (ValidationError, IntegrityError):
                        # Race condition: phone was created between lookup and create
                        # Fall back to lookup again. If no matching customer exists,
                        # the failure was unrelated (for example a bad PK sequence),
                        # so preserve the original error.
                        fallback = await customer_service.repository.get_by_phone(order_data.customer_phone)
                        if not fallback:
                            raise
                        order_data.customer_id = fallback.id
                
                if getattr(order_data, 'customer_address', None):
                    # Check if customer already has this exact address
                    existing_customer = await customer_service.repository.get_by_id(order_data.customer_id)
                    existing_match = None
                    if existing_customer and existing_customer.addresses:
                        existing_match = next(
                            (a for a in existing_customer.addresses if a.address == order_data.customer_address),
                            None
                        )
                    if existing_match:
                        order_data.address_id = existing_match.id
                    else:
                        new_addr = await customer_service.add_address(order_data.customer_id, CustomerAddressCreate(address=order_data.customer_address))
                        order_data.address_id = new_addr.id

            redemption = None
            order_items = list(order_data.items)
            if order_data.loyalty_rule_id:
                redemption = await select_redemption(
                    self.db, str(order_data.loyalty_rule_id), redeeming_customer, order_data.customer_phone,
                )
                if (redemption.points_required != order_data.loyalty_expected_points
                        or redemption.reward_value != order_data.loyalty_expected_value):
                    raise ValidationError("مكافأة النقاط اتغيرت. حدّث رصيدك واختارها من جديد")
                if order_data.customer_id != redeeming_customer["customer_id"]:
                    raise ValidationError("بيانات العميل لا تطابق الحساب المسجل")
                if redemption.product_id:
                    order_items.append(schemas.OrderItemCreate(
                        product_id=redemption.product_id, quantity=1, unit_price=redemption.reward_value,
                    ))
            await self._validate_order_items(order_items)

            # 1. Prepare Pricing Request
            pricing_items = [
                PricingItem(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price
                ) for item in order_items
            ]
            
            pricing_req = PricingRequest(
                items=pricing_items,
                order_type=order_data.order_type,
                delivery_fee=order_data.delivery_fee,
                offer_code=order_data.offer_code,
                customer_phone=order_data.customer_phone,
                cashier_id=current_user_id if order_data.source == models.OrderSource.CASHIER else None,
                manual_discount_type=getattr(order_data, 'manual_discount_type', None),
                manual_discount_value=getattr(order_data, 'manual_discount_value', None)
            )
            
            # 2. Get Pricing Calculation
            pricing_res = await self.pricing_service.calculate_price(pricing_req)
            
            # 3. Create Order Object
            next_number = await self.repository.get_next_order_number()
            order_dict = order_data.model_dump(exclude={'items', 'offer_code', 'source', 'customer_address', 'order_number', 'order_date', 'manual_discount_type', 'manual_discount_value', 'discount_reason', 'loyalty_rule_id', 'loyalty_expected_points', 'loyalty_expected_value', 'cash_received', 'digital_payment_verified'})
            order = models.Order(**order_dict)
            if order_data.digital_payment_verified:
                order.digital_payment_verified_at = datetime.now(UTC)
                order.digital_payment_verified_by_user_id = current_user_id
            
            # 4. Fill calculated financials and metadata
            order.order_number = getattr(order_data, 'order_number', None) or next_number
            order.order_date = getattr(order_data, 'order_date', None) or self.repository.get_business_date()
            order.order_source = order_data.source
            order.cash_tracking_enabled = True
            order.created_by_user_id = current_user_id
            
            if order_data.source == models.OrderSource.CASHIER:
                order.order_status = models.OrderStatus.CONFIRMED
            else:
                order.order_status = models.OrderStatus.NEW
            
            order.subtotal = pricing_res.subtotal
            loyalty_discount = Decimal("0.00")
            if redemption:
                if pricing_res.subtotal - pricing_res.discount_amount < redemption.reward_value:
                    raise ValidationError("قيمة الطلب بعد الخصومات لا تكفي لتطبيق مكافأة النقاط")
                loyalty_discount = redemption.reward_value
                order.loyalty_rule_id = redemption.rule_id
                order.loyalty_reward_type = redemption.reward_type
                order.loyalty_points_spent = redemption.points_required
                order.loyalty_discount_amount = loyalty_discount
                order.loyalty_product_id = redemption.product_id
                order.loyalty_product_name = redemption.product_name
                order.loyalty_variant_name = redemption.variant_name
                order.loyalty_status = "reserved"
                order.loyalty_reserved_at = redemption.selected_at.replace(tzinfo=None)
            order.discount_amount = pricing_res.discount_amount + loyalty_discount
            order.discount_type = getattr(order_data, 'manual_discount_type', None)
            order.discount_value = getattr(order_data, 'manual_discount_value', None)
            order.discount_reason = getattr(order_data, 'discount_reason', None)
            order.delivery_fee = pricing_res.delivery_fee
            order.total_amount = pricing_res.total_amount - loyalty_discount
            
            # 5. Add Items
            for item_data in order_items:
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
            if order_data.cash_received:
                from app.modules.shifts.cash_custody import record_customer_collection
                from app.modules.users.models import User

                actor = await self.db.get(User, current_user_id)
                if not actor:
                    raise ValidationError("تعذر تحديد الكاشير الذي استلم النقد")
                await record_customer_collection(
                    self.db, order.id, actor, f"order:{order.id}:cash-on-create"
                )
            order = await self.get_order(order.id)
            if order.order_status == OrderStatus.CONFIRMED:
                await award_order_points(self.db, order)
            
            # Record Outbox Event
            order_schema = schemas.OrderResponse.model_validate(order)
            payload_data = order_schema.model_dump(mode='json')
            
            # 8. Trigger Sync and Notify
            await order_events_manager.emit({
                "type": "NEW_ORDER",
                "event": "order.created",
                "data": payload_data
            })
            await self.notifications.enqueue(payload_data, "created")
            
            return order

    async def get_order(self, order_id: int) -> models.Order:
        order = await self.repository.get_by_id(order_id)
        if not order:
            raise NotFoundError(f"Order with ID {order_id}")
        return order

    async def list_orders_paginated(
        self,
        source: str | None = None,
        status: str | None = None,
        order_type: str | None = None,
        is_printed: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        cashier_id: int | None = None,
        shift=None,
        payment_method: PaymentMethod | None = None,
        search: str | None = None,
    ) -> tuple[int, list[models.Order]]:
        return await self.repository.list_orders_paginated(
            source=source,
            status=status,
            order_type=order_type,
            is_printed=is_printed,
            page=page,
            page_size=page_size,
            cashier_id=cashier_id,
            shift=shift,
            payment_method=payment_method,
            search=search,
        )

    async def list_orders(self, cashier_id: int | None = None, **kwargs) -> list[models.Order]:
        return await self.repository.list_orders(cashier_id=cashier_id, **kwargs)

    async def list_orders_for_business_day(self, source: str | None = None, status: str | None = None, order_type: str | None = None, cashier_id: int | None = None) -> list[models.Order]:
        return await self.repository.list_dashboard_orders(
            source=source,
            status=status,
            order_type=order_type,
            cashier_id=cashier_id,
        )

    async def mark_order_printed(self, order_id: int) -> models.Order:
        async with self._transaction_scope():
            order = await self.get_order(order_id)
            order.is_printed = True
            await self.repository.save(order)
            completed_order = await self.get_order(order.id)
            completed_schema = schemas.OrderResponse.model_validate(completed_order)
            payload_data = completed_schema.model_dump(mode='json')
            await order_events_manager.emit({
                "type": "ORDER_UPDATED",
                "event": "order.updated",
                "data": payload_data
            })
            return completed_order

    async def request_cancellation(self, order_id: int, current_user_id: int) -> models.OrderCancellationRequest:
        async with self._transaction_scope():
            await self.db.scalar(select(models.Order.id).where(models.Order.id == order_id).with_for_update())
            order = await self.get_order(order_id)
            if not order.can_transition_to(OrderStatus.CANCELLED):
                raise ValidationError("لا يمكن إلغاء طلب بحالته الحالية")
            pending = await self.db.scalar(select(models.OrderCancellationRequest).where(
                models.OrderCancellationRequest.order_id == order_id,
                models.OrderCancellationRequest.status == "pending",
            ).with_for_update())
            if pending:
                return pending
            request = models.OrderCancellationRequest(
                order_id=order_id, requested_by_user_id=current_user_id, status="pending",
            )
            self.db.add(request)
            await self.db.flush()
        await self.db.commit()
        await order_events_manager.emit({
            "type": "CANCELLATION_REQUEST_UPDATED", "data": {"order_id": order_id},
        }, channel="admin")
        return request

    async def list_pending_cancellations(self) -> list[dict]:
        from app.modules.users.models import User

        rows = (await self.db.execute(
            select(models.OrderCancellationRequest, models.Order.order_number, User.full_name, User.username)
            .join(models.Order, models.Order.id == models.OrderCancellationRequest.order_id)
            .join(User, User.id == models.OrderCancellationRequest.requested_by_user_id)
            .where(models.OrderCancellationRequest.status == "pending")
            .order_by(models.OrderCancellationRequest.requested_at.desc())
        )).all()
        return [
            {
                "id": request.id, "order_id": request.order_id, "order_number": order_number,
                "requester_name": full_name or username, "status": request.status,
                "requested_at": request.requested_at,
            }
            for request, order_number, full_name, username in rows
        ]

    async def reject_cancellation(self, request_id: int, admin_id: int) -> None:
        async with self._transaction_scope():
            request = await self.db.scalar(select(models.OrderCancellationRequest).where(
                models.OrderCancellationRequest.id == request_id,
            ).with_for_update())
            if not request or request.status != "pending":
                raise ValidationError("طلب الإلغاء غير موجود أو تمت مراجعته")
            request.status = "rejected"
            request.decided_by_user_id = admin_id
            request.decided_at = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
            await self.db.flush()
        await self.db.commit()
        await order_events_manager.emit({
            "type": "CANCELLATION_REQUEST_UPDATED", "data": {"order_id": request.order_id},
        })

    async def approve_cancellation(self, request_id: int, admin_id: int) -> models.Order:
        request = await self.db.get(models.OrderCancellationRequest, request_id)
        if not request:
            raise ValidationError("طلب الإلغاء غير موجود")
        return await self.update_order_status(
            request.order_id, schemas.OrderUpdate(order_status=OrderStatus.CANCELLED),
            current_user_id=admin_id, cancellation_request_id=request_id,
        )

    async def update_order_status(self, order_id: int, update_data: schemas.OrderUpdate, current_user_id: int | None = None,
                                  cancellation_request_id: int | None = None) -> models.Order:
        async with self._transaction_scope():
            await self.db.scalar(select(models.Order.id).where(models.Order.id == order_id).with_for_update())
            order = await self.get_order(order_id)
            if update_data.digital_payment_verified and not (
                update_data.order_status == OrderStatus.CONFIRMED
                and order.order_status == OrderStatus.NEW
                and order.payment_method in (PaymentMethod.INSTAPAY, PaymentMethod.WALLET)
            ):
                raise ValidationError("تأكيد التحويل متاح عند قبول طلب رقمي جديد فقط")
            if update_data.order_status == OrderStatus.CANCELLED:
                from app.modules.shifts.cash_custody import (
                    assert_financial_change_clear,
                )
                await assert_financial_change_clear(self.db, order)
            if "delivery_person_id" in update_data.model_fields_set and update_data.delivery_person_id != order.delivery_person_id:
                from app.modules.shifts.cash_custody import (
                    assert_financial_change_clear,
                )
                await assert_financial_change_clear(self.db, order)
            pending_cancellation = await self.db.scalar(select(models.OrderCancellationRequest).where(
                models.OrderCancellationRequest.order_id == order_id,
                models.OrderCancellationRequest.status == "pending",
            ).with_for_update())
            if cancellation_request_id and (
                not pending_cancellation or pending_cancellation.id != cancellation_request_id
                or update_data.order_status != OrderStatus.CANCELLED
            ):
                raise ValidationError("طلب الإلغاء غير موجود أو تمت مراجعته")
            status_changed = bool(update_data.order_status and order.order_status != update_data.order_status)
            if update_data.order_status and order.order_status != update_data.order_status:
                if update_data.order_status == OrderStatus.CONFIRMED and order.order_source == OrderSource.ONLINE:
                    from app.modules.shifts.cash_custody import active_shift
                    from app.modules.users.models import User

                    actor = await self.db.get(User, current_user_id) if current_user_id else None
                    if actor and actor.role == UserRole.CASHIER:
                        await active_shift(self.db, actor.id)
                    if order.payment_method in (PaymentMethod.INSTAPAY, PaymentMethod.WALLET):
                        if not update_data.digital_payment_verified or not actor or actor.role != UserRole.CASHIER:
                            raise ValidationError("الكاشير لازم يتأكد إن التحويل وصل قبل قبول الطلب")
                        order.digital_payment_verified_at = datetime.now(UTC)
                        order.digital_payment_verified_by_user_id = actor.id
                target_rider_id = update_data.delivery_person_id or order.delivery_person_id
                if (
                    update_data.order_status == OrderStatus.CONFIRMED
                    and order.order_type == OrderType.DELIVERY
                    and not target_rider_id
                ):
                    raise ValidationError("يجب إسناد مندوب قبل قبول طلب الدليفري")
                if order.order_type == OrderType.DELIVERY and target_rider_id:
                    from app.modules.users.models import User
                    rider = await self.db.get(User, target_rider_id)
                    if not rider or rider.role != UserRole.DELIVERY or not rider.is_active or rider.is_deleted:
                        raise ValidationError("المندوب المختار غير متاح")
                if update_data.order_status == OrderStatus.OUT_FOR_DELIVERY and not target_rider_id:
                    raise ValidationError("A delivery rider must be assigned before dispatch")
                if not order.can_transition_to(update_data.order_status):
                    raise ValidationError(f"Invalid status transition from {order.order_status} to {update_data.order_status}")
                
                # If an online order is confirmed by a cashier, assign it to them
                if (
                    update_data.order_status == OrderStatus.CONFIRMED
                    and order.order_source == OrderSource.ONLINE
                    and not order.created_by_user_id
                    and current_user_id
                ):
                    order.created_by_user_id = current_user_id
            
            updated_order = await self.repository.update(order, update_data, changed_by_user_id=current_user_id)
            if status_changed and pending_cancellation:
                if updated_order.order_status == OrderStatus.CANCELLED:
                    pending_cancellation.status = "approved"
                elif updated_order.order_status in (OrderStatus.COMPLETED, OrderStatus.DELIVERED):
                    pending_cancellation.status = "rejected"
                if pending_cancellation.status != "pending":
                    pending_cancellation.decided_by_user_id = current_user_id
                    pending_cancellation.decided_at = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
            await self.db.flush()
            if status_changed and updated_order.order_status == OrderStatus.CONFIRMED:
                if updated_order.loyalty_status == "reserved":
                    updated_order.loyalty_status = "consumed"
                await award_order_points(self.db, updated_order)
            elif status_changed and updated_order.order_status == OrderStatus.CANCELLED:
                if updated_order.loyalty_status in ("reserved", "consumed"):
                    updated_order.loyalty_status = "reversed"
                await reverse_order_points(self.db, updated_order.id)
            completed_order = await self.get_order(updated_order.id)
            completed_schema = schemas.OrderResponse.model_validate(completed_order)
            payload_data = completed_schema.model_dump(mode='json')
            await self.notifications.enqueue(payload_data, "status_changed" if status_changed else "updated")
        if pending_cancellation and pending_cancellation.status != "pending":
            await self.db.commit()
        await order_events_manager.emit({
            "type": "ORDER_UPDATED",
            "event": "order.updated",
            "data": payload_data
        })
        if pending_cancellation and pending_cancellation.status != "pending":
            await order_events_manager.emit({
                "type": "CANCELLATION_REQUEST_UPDATED", "data": {"order_id": order_id},
            })
        return completed_order

    async def update_order(self, order_id: int, update_data: schemas.OrderUpdateFull, current_user_id: int | None = None) -> models.Order:
        async with self._transaction_scope():
            await self.db.scalar(select(models.Order.id).where(models.Order.id == order_id).with_for_update())
            order = await self.get_order(order_id)
            if order.order_status in [models.OrderStatus.COMPLETED, models.OrderStatus.DELIVERED, models.OrderStatus.CANCELLED]:
                raise ValidationError(f"Cannot update an order that is {order.order_status.value}")
            target_type = update_data.order_type or order.order_type
            if target_type == OrderType.PHONE_RESERVATION:
                from app.modules.customer.phone import normalize_egyptian_phone
                phone = normalize_egyptian_phone(update_data.customer_phone or order.customer_phone)
                if len(phone) != 11 or not phone.startswith("01"):
                    raise ValidationError("رقم تليفون العميل مطلوب لحجز التلفون ويجب أن يكون 11 رقمًا")
                update_data.customer_phone = phone
            
            old_state = {
                "total_amount": order.total_amount,
                "payment_method": order.payment_method,
                "order_type": order.order_type,
                "delivery_person_id": order.delivery_person_id,
                "discount_amount": order.discount_amount,
                "delivery_fee": order.delivery_fee,
                "items_count": sum(i.quantity for i in order.items) if order.items else 0,
                "customer_name": order.customer_name,
                "customer_phone": order.customer_phone
            }
            
            if update_data.customer_phone or update_data.customer_name or getattr(update_data, 'customer_address', None):
                target_phone = update_data.customer_phone or order.customer_phone
                target_name = update_data.customer_name or order.customer_name
                if update_data.customer_address and not (target_phone and target_name):
                    # Older/guest orders may have a linked customer without both
                    # display fields. Resolve from that customer before saving an
                    # address; never return 200 for an address we did not apply.
                    from app.modules.customer.repository import CustomerRepository

                    linked_customer_id = update_data.customer_id or order.customer_id
                    linked_customer = (
                        await CustomerRepository(self.db).get_by_id(linked_customer_id)
                        if linked_customer_id else None
                    )
                    if linked_customer:
                        target_phone = target_phone or linked_customer.phone_number
                        target_name = target_name or linked_customer.name
                    if not (target_phone and target_name):
                        raise ValidationError("لا يمكن حفظ العنوان بدون بيانات عميل مرتبطة بالطلب")
                if target_phone and target_name:
                    from app.modules.customer.phone import normalize_egyptian_phone
                    from app.modules.customer.schemas import (
                        CustomerAddressCreate,
                        CustomerCreate,
                    )
                    from app.modules.customer.service import CustomerService
                    customer_service = CustomerService(self.db, self.redis)
                    try:
                        existing_cust = await customer_service.get_customer_by_phone(target_phone)
                        update_data.customer_id = existing_cust.id
                        
                        # Update local customer name if different, and push sync event
                        if existing_cust.name != target_name:
                            existing_cust.name = target_name
                            self.db.add(existing_cust)
                            
                            
                    except NotFoundError:
                        # A changed phone number belongs to the customer already
                        # linked to this order.  Keep that identity instead of
                        # silently creating a second customer record.
                        linked_customer = (
                            await customer_service.repository.get_by_id(order.customer_id)
                            if order.customer_id else None
                        )
                        normalized_phone = normalize_egyptian_phone(target_phone) or target_phone.strip()
                        if linked_customer:
                            linked_customer.name = target_name
                            linked_customer.phone_number = normalized_phone
                            self.db.add(linked_customer)
                            update_data.customer_id = linked_customer.id
                        else:
                            new_cust = await customer_service.create_customer(CustomerCreate(
                                name=target_name,
                                phone_number=target_phone
                            ))
                            update_data.customer_id = new_cust.id
                    if getattr(update_data, 'customer_address', None):
                        # Check if customer already has this exact address
                        existing_customer = await customer_service.repository.get_by_id(update_data.customer_id)
                        existing_match = None
                        if existing_customer and existing_customer.addresses:
                            existing_match = next(
                                (a for a in existing_customer.addresses if a.address == update_data.customer_address),
                                None
                            )
                        if existing_match:
                            self._apply_resolved_address(order, update_data, existing_match)
                        else:
                            new_addr = await customer_service.add_address(update_data.customer_id, CustomerAddressCreate(address=update_data.customer_address))
                            self._apply_resolved_address(order, update_data, new_addr)

            needs_reprice = False
            if update_data.delivery_fee is not None and update_data.delivery_fee != order.delivery_fee:
                order.delivery_fee = update_data.delivery_fee
                needs_reprice = True
            if hasattr(update_data, 'order_type') and update_data.order_type is not None and update_data.order_type != order.order_type:
                order.order_type = update_data.order_type
                needs_reprice = True
            if update_data.items is not None:
                needs_reprice = True
            
            # Check if discount fields are provided in the update (even if None, to clear them)
            provided_fields = update_data.model_fields_set
            if 'manual_discount_type' in provided_fields or 'manual_discount_value' in provided_fields:
                needs_reprice = True
            
            if needs_reprice:
                applied_offer = order.applied_offer
                existing_offer_code = applied_offer["code"] if applied_offer else None
                if update_data.items is not None:
                    await self._validate_order_items(update_data.items)
                    pricing_items = [PricingItem(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price) for it in update_data.items]
                else:
                    pricing_items = [PricingItem(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price) for it in order.items]
                
                # Use updated discount if provided, else keep existing
                disc_type = update_data.manual_discount_type if 'manual_discount_type' in provided_fields else order.discount_type
                disc_value = update_data.manual_discount_value if 'manual_discount_value' in provided_fields else order.discount_value

                pricing_req = PricingRequest(
                    items=pricing_items, order_type=order.order_type, delivery_fee=order.delivery_fee, 
                    offer_code=existing_offer_code, customer_phone=order.customer_phone, cashier_id=current_user_id,
                    redeemed_order_id=order.id if existing_offer_code else None,
                    manual_discount_type=disc_type,
                    manual_discount_value=disc_value
                )
                pricing_res = await self.pricing_service.calculate_price(pricing_req)
                
                if pricing_res.discount_amount < Decimal("0.00") or pricing_res.discount_amount > pricing_res.subtotal or pricing_res.total_amount < Decimal("0.00"):
                    raise ValidationError("Invalid financial state after recalculating.")
                
                if update_data.items is not None:
                    order.items.clear()
                    for item_data in update_data.items:
                        item = models.OrderItem(**item_data.model_dump())
                        item.total_price = item.quantity * item.unit_price
                        order.items.append(item)
                
                order.subtotal = pricing_res.subtotal
                loyalty_discount = Decimal("0.00")
                if order.loyalty_status in ("reserved", "consumed"):
                    reward_value = Decimal(order.loyalty_discount_amount)
                    gift_present = order.loyalty_reward_type != "free_product" or any(
                        item.product_id == order.loyalty_product_id and Decimal(item.unit_price) == reward_value
                        for item in order.items
                    )
                    if gift_present and pricing_res.subtotal - pricing_res.discount_amount >= reward_value:
                        loyalty_discount = reward_value
                    else:
                        order.loyalty_status = "reversed"
                order.loyalty_discount_amount = loyalty_discount
                order.discount_amount = pricing_res.discount_amount + loyalty_discount
                order.discount_type = disc_type
                order.discount_value = disc_value
                order.delivery_fee = pricing_res.delivery_fee
                order.total_amount = pricing_res.total_amount - loyalty_discount
            
            # Update discount reason if provided
            if 'discount_reason' in provided_fields:
                order.discount_reason = update_data.discount_reason

            if (old_state["total_amount"] != order.total_amount
                    or old_state["payment_method"] != (update_data.payment_method or order.payment_method)
                    or old_state["order_type"] != order.order_type
                    or ("delivery_person_id" in provided_fields and old_state["delivery_person_id"] != update_data.delivery_person_id)):
                from app.modules.shifts.cash_custody import (
                    assert_financial_change_clear,
                )
                await assert_financial_change_clear(self.db, order)
            target_method = update_data.payment_method or order.payment_method
            digital_changed = (
                old_state["payment_method"] != target_method
                or old_state["total_amount"] != order.total_amount
            )
            if update_data.digital_payment_verified and target_method not in (PaymentMethod.INSTAPAY, PaymentMethod.WALLET):
                raise ValidationError("تأكيد التحويل متاح للطلب الرقمي فقط")
            if update_data.digital_payment_verified and order.order_status == OrderStatus.NEW:
                raise ValidationError("أكد وصول التحويل عند قبول الطلب، بعد اكتمال بياناته")
            if digital_changed:
                if target_method in (PaymentMethod.INSTAPAY, PaymentMethod.WALLET) and order.order_status != OrderStatus.NEW:
                    if not update_data.digital_payment_verified:
                        raise ValidationError("تأكد من وصول مبلغ التحويل الجديد قبل حفظ التعديل")
                    from app.modules.shifts.cash_custody import active_shift
                    from app.modules.users.models import User

                    actor = await self.db.get(User, current_user_id) if current_user_id else None
                    if not actor or actor.role != UserRole.CASHIER:
                        raise ValidationError("الكاشير فقط يؤكد وصول التحويل")
                    await active_shift(self.db, actor.id)
                    order.digital_payment_verified_at = datetime.now(UTC)
                    order.digital_payment_verified_by_user_id = actor.id
                else:
                    order.digital_payment_verified_at = None
                    order.digital_payment_verified_by_user_id = None
            elif update_data.digital_payment_verified:
                from app.modules.shifts.cash_custody import active_shift
                from app.modules.users.models import User

                actor = await self.db.get(User, current_user_id) if current_user_id else None
                if not actor or actor.role != UserRole.CASHIER:
                    raise ValidationError("الكاشير فقط يؤكد وصول التحويل")
                await active_shift(self.db, actor.id)
                order.digital_payment_verified_at = datetime.now(UTC)
                order.digital_payment_verified_by_user_id = actor.id
            updated_order = await self.repository.update_order_full(order, update_data, changed_by_user_id=current_user_id)
            
            # Track changes
            changes = []
            if old_state["total_amount"] != updated_order.total_amount:
                changes.append(f"تعديل الإجمالي من {float(old_state['total_amount']):.2f} إلى {float(updated_order.total_amount):.2f}")
            if old_state["discount_amount"] != updated_order.discount_amount:
                changes.append(f"تعديل الخصم من {float(old_state['discount_amount']):.2f} إلى {float(updated_order.discount_amount):.2f}")
            if old_state["delivery_fee"] != updated_order.delivery_fee:
                changes.append(f"تعديل خدمة التوصيل من {float(old_state['delivery_fee']):.2f} إلى {float(updated_order.delivery_fee):.2f}")
            if old_state["payment_method"] != updated_order.payment_method:
                changes.append(
                    f"تعديل وسيلة الدفع من {old_state['payment_method'].value} "
                    f"إلى {updated_order.payment_method.value}"
                )
            if update_data.digital_payment_verified:
                changes.append("الكاشير أكد وصول مبلغ التحويل بعد تعديل الطلب")
            new_items_count = sum(i.quantity for i in updated_order.items) if updated_order.items else 0
            if old_state["items_count"] != new_items_count:
                changes.append(f"تعديل الأصناف (من {old_state['items_count']} صنف إلى {new_items_count} صنف)")
            if old_state["customer_name"] != updated_order.customer_name:
                changes.append(f"تعديل العميل من '{old_state['customer_name'] or 'نقدي'}' إلى '{updated_order.customer_name or 'نقدي'}'")

            if changes:
                mod_history = models.OrderModificationHistory(
                    order_id=updated_order.id,
                    changed_by_user_id=current_user_id,
                    changes=changes
                )
                self.db.add(mod_history)
                updated_order.modifications.append(mod_history)

            await self.db.flush()
            await recalculate_order_points(self.db, updated_order)
            
            completed_order = await self.get_order(updated_order.id)
            completed_schema = schemas.OrderResponse.model_validate(completed_order)
            payload_data = completed_schema.model_dump(mode='json')
            await self.notifications.enqueue(payload_data, "updated")
        await order_events_manager.emit({
            "type": "ORDER_UPDATED",
            "event": "order.updated",
            "data": payload_data
        })
        return completed_order

    @staticmethod
    def _apply_resolved_address(order, update_data, address) -> None:
        """Synchronize the address FK and loaded relationship for the PATCH response."""
        update_data.address_id = address.id
        order.address = address

    async def get_today_stats(self) -> dict:
        return await self.repository.get_today_stats()

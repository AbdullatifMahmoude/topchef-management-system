import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError as PydanticValidationError

from app.core.enums import DiscountType, OrderSource, OrderType, ProductType
from app.core.exceptions import ValidationError
from app.modules.menu.models import Category, Product, Variant
from app.modules.offer.models import Offer
from app.modules.orders.schemas import OrderCreate, OrderItemCreate
from app.modules.orders.service import OrderService
from app.modules.pricing.domain import FinancialSnapshot
from app.modules.pricing.schemas import PricingItem, PricingRequest
from app.modules.pricing.service import PricingService
from app.modules.shifts.service import restaurant_sales_amount


def order_payload(**overrides):
    payload = {
        "order_type": OrderType.TAKEAWAY,
        "source": OrderSource.CASHIER,
        "items": [{"product_id": 1, "quantity": 1, "unit_price": "50.00"}],
    }
    payload.update(overrides)
    return payload


class FakeOfferService:
    def __init__(self, *, waive_delivery_fee=False):
        self.waive_delivery_fee = waive_delivery_fee

    async def apply_offer(self, *args, **kwargs):
        return SimpleNamespace(
            discount_amount=Decimal("0.00"),
            waive_delivery_fee=self.waive_delivery_fee,
        )


class FinancialBusinessRuleTests(unittest.IsolatedAsyncioTestCase):
    def test_manual_percentage_cannot_exceed_one_hundred(self):
        with self.assertRaises(PydanticValidationError):
            OrderCreate.model_validate(order_payload(
                manual_discount_type=DiscountType.PERCENTAGE,
                manual_discount_value="101",
            ))

    def test_offer_and_manual_discount_cannot_stack(self):
        with self.assertRaises(PydanticValidationError):
            OrderCreate.model_validate(order_payload(
                offer_code="SAVE10",
                manual_discount_type=DiscountType.FIXED,
                manual_discount_value="5",
            ))

    def test_currency_rounding_is_half_up(self):
        snapshot = FinancialSnapshot.calculate(Decimal("1.005"))
        self.assertEqual(snapshot.total_amount, Decimal("1.01"))

    async def test_free_delivery_offer_rejects_non_delivery_order(self):
        service = PricingService(object(), offer_service=FakeOfferService(waive_delivery_fee=True))
        request = PricingRequest(
            items=[PricingItem(product_id=1, quantity=1, unit_price=Decimal("50"))],
            order_type=OrderType.HALL,
            offer_code="FREEDELIVERY",
        )
        with self.assertRaises(ValidationError):
            await service.calculate_price(request)

    async def test_order_rejects_client_price_not_found_in_product_variants(self):
        category = Category(id=1, cat_name="Main", is_active=True, is_deleted=False)
        product = Product(
            id=1,
            cat_id=1,
            product_name="Meal",
            product_type=ProductType.SIMPLE,
            is_available=True,
            is_deleted=False,
        )
        product.category = category
        product.variants = [Variant(id=1, product_id=1, name="Normal", price=Decimal("50.00"), is_deleted=False)]
        service = OrderService(object())
        with patch("app.modules.menu.service.ProductService.get_products_by_ids", new=AsyncMock(return_value=[product])):
            with self.assertRaises(ValidationError):
                await service._validate_order_items([
                    OrderItemCreate(product_id=1, quantity=1, unit_price=Decimal("1.00"))
                ])

    async def test_order_accepts_exact_database_variant_price(self):
        category = Category(id=1, cat_name="Main", is_active=True, is_deleted=False)
        product = Product(
            id=1,
            cat_id=1,
            product_name="Meal",
            product_type=ProductType.SIMPLE,
            is_available=True,
            is_deleted=False,
        )
        product.category = category
        product.variants = [Variant(id=1, product_id=1, name="Normal", price=Decimal("50.00"), is_deleted=False)]
        service = OrderService(object())
        with patch("app.modules.menu.service.ProductService.get_products_by_ids", new=AsyncMock(return_value=[product])):
            await service._validate_order_items([
                OrderItemCreate(product_id=1, quantity=1, unit_price=Decimal("50.00"))
            ])

    def test_offer_calendar_uses_cairo_wall_clock(self):
        cairo_now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        offer = Offer(
            code="CAIRO",
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("10"),
            valid_from=cairo_now - timedelta(minutes=1),
            valid_to=cairo_now + timedelta(minutes=1),
            is_active=True,
            is_deleted=False,
        )
        self.assertTrue(offer.is_started())
        self.assertFalse(offer.is_expired())

    def test_restaurant_sales_excludes_delivery_fee_only(self):
        delivery = SimpleNamespace(order_type=OrderType.DELIVERY, total_amount=Decimal("120"), delivery_fee=Decimal("20"))
        hall = SimpleNamespace(order_type=OrderType.HALL, total_amount=Decimal("120"), delivery_fee=Decimal("20"))
        self.assertEqual(restaurant_sales_amount(delivery), Decimal("100"))
        self.assertEqual(restaurant_sales_amount(hall), Decimal("120"))

    def test_shift_cash_expected_uses_restaurant_share_after_rider_is_paid(self):
        opening_cash = Decimal("100")
        expense = Decimal("10")
        cash_delivery_order = SimpleNamespace(
            order_type=OrderType.DELIVERY,
            total_amount=Decimal("120"),
            delivery_fee=Decimal("20"),
        )
        expected_cash = opening_cash + restaurant_sales_amount(cash_delivery_order) - expense
        self.assertEqual(expected_cash, Decimal("190"))

    def test_all_report_queries_condition_delivery_fee_on_delivery_type(self):
        report_source = open("app/modules/report/service.py", encoding="utf-8").read()
        repository_source = open("app/modules/orders/repository.py", encoding="utf-8").read()
        self.assertGreaterEqual(report_source.count("Order.order_type == OrderType.DELIVERY"), 4)
        self.assertGreaterEqual(repository_source.count("models.Order.order_type == OrderType.DELIVERY"), 2)

    def test_report_before_discount_includes_hall_service_fee(self):
        report_source = open("app/modules/report/service.py", encoding="utf-8").read()
        self.assertIn("Order.subtotal + hall_service_fee", report_source)

    def test_edit_repricing_keeps_existing_offer_and_does_not_redeem_again(self):
        source = open("app/modules/orders/service.py", encoding="utf-8").read()
        self.assertIn("offer_code=existing_offer_code", source)
        self.assertIn("redeemed_order_id=order.id if existing_offer_code else None", source)

    def test_confirmation_fetches_authoritative_pricing(self):
        source = open("app/frontend/cashier/js/cashier.js", encoding="utf-8").read()
        confirm_start = source.index("async function confirmOrder()")
        modal_start = source.index("function showConfirmModal", confirm_start)
        confirm_source = source[confirm_start:modal_start]
        self.assertIn('apiFetch("/pricing/preview"', confirm_source)
        self.assertIn("pricing.total_amount", confirm_source)


if __name__ == "__main__":
    unittest.main()

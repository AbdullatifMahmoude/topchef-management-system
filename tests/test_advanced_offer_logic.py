import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.core.enums import DiscountType, ProductType
from app.modules.users.models import User  # registers relationship target for SQLAlchemy tests
from app.modules.menu.models import Product
from app.modules.offer.models import Offer
from app.modules.offer.service import OfferService


class FakeDB:
    def in_transaction(self):
        return False

    @asynccontextmanager
    async def begin(self):
        yield

    async def execute(self, _query):
        class Result:
            def scalars(self):
                return self
            def all(self):
                return [1]
        return Result()


class FakeRepository:
    def __init__(self, offer):
        self.offer = offer

    async def get_by_code(self, code, lock=False):
        return self.offer if code == self.offer.code else None


def product(product_id):
    return Product(id=product_id, cat_id=1, product_name=f"P{product_id}", product_type=ProductType.SIMPLE, is_available=True, is_deleted=False)


def item(product_id, quantity, price):
    return SimpleNamespace(product_id=product_id, quantity=quantity, unit_price=Decimal(str(price)))


def offer(dtype, value=1, product_ids=(1,), rules=None):
    model = Offer(
        offer_id=1, code="TEST", display_name="Test", discount_type=dtype,
            discount_value=Decimal(str(value)), valid_from=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
            valid_to=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1), current_usage=0,
        is_active=True, is_deleted=False, rules=rules or {}, version=1,
    )
    model.products = [product(pid) for pid in product_ids]
    return model


async def calculate(model, items, subtotal=None):
    service = OfferService(FakeDB())
    service.repository = FakeRepository(model)
    subtotal = subtotal or sum((entry.unit_price * entry.quantity for entry in items), Decimal("0"))
    return await service.apply_offer("test", subtotal, items, commit_usage=False)


class AdvancedOfferLogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_offer_treats_unflushed_usage_counter_as_zero(self):
        model = offer(DiscountType.PERCENTAGE, 10)
        model.usage_limit = 1
        model.current_usage = None

        OfferService._validate_configuration(model)

        self.assertFalse(model.is_usage_limit_reached())

    async def test_percentage_only_discounts_selected_products(self):
        result = await calculate(offer(DiscountType.PERCENTAGE, 20), [item(1, 2, 50), item(2, 1, 100)])
        self.assertEqual(result.discount_amount, Decimal("20.00"))

    async def test_combo_repeats_for_each_complete_bundle(self):
        model = offer(DiscountType.COMBO, product_ids=(1, 2), rules={"combo_price": 70, "requirements": [{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 1}]})
        result = await calculate(model, [item(1, 2, 50), item(2, 2, 40)])
        self.assertEqual(result.discount_amount, Decimal("40.00"))

    async def test_buy_x_get_y_discounts_reward_units(self):
        model = offer(DiscountType.BUY_X_GET_Y, product_ids=(1, 2), rules={"buy_product_ids": [1], "get_product_ids": [2], "buy_quantity": 2, "get_quantity": 1, "reward_percent": 100})
        result = await calculate(model, [item(1, 2, 50), item(2, 1, 20)])
        self.assertEqual(result.discount_amount, Decimal("20.00"))

    async def test_quantity_discount_requires_threshold(self):
        model = offer(DiscountType.QUANTITY_DISCOUNT, 15, rules={"quantity_required": 3})
        result = await calculate(model, [item(1, 3, 100)])
        self.assertEqual(result.discount_amount, Decimal("45.00"))

    async def test_free_delivery_sets_waiver_without_product_discount(self):
        result = await calculate(offer(DiscountType.FREE_DELIVERY, product_ids=()), [item(1, 1, 100)])
        self.assertEqual(result.discount_amount, Decimal("0.00"))
        self.assertTrue(result.waive_delivery_fee)

    async def test_category_discount_only_uses_category_products(self):
        model = offer(DiscountType.CATEGORY_DISCOUNT, 10, product_ids=(), rules={"category_ids": [1], "discount_mode": "percentage"})
        result = await calculate(model, [item(1, 1, 100), item(2, 1, 100)])
        self.assertEqual(result.discount_amount, Decimal("10.00"))

    async def test_happy_hour_handles_daily_time_window(self):
        model = offer(DiscountType.HAPPY_HOUR, 25, rules={"start_time": "00:00", "end_time": "23:59"})
        result = await calculate(model, [item(1, 1, 100)])
        self.assertEqual(result.discount_amount, Decimal("25.00"))


if __name__ == "__main__":
    unittest.main()

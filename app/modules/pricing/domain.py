from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel


class FinancialSnapshot(BaseModel):
    """
    A pure domain object representing a financial state of an order/preview.
    Decoupled from SQLAlchemy models.
    """
    subtotal: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    delivery_fee: Decimal = Decimal("0.00")
    total_amount: Decimal = Decimal("0.00")

    @classmethod
    def calculate(
        cls, 
        subtotal: Decimal, 
        discount_amount: Decimal = Decimal("0.00"), 
        delivery_fee: Decimal = Decimal("0.00")
    ) -> "FinancialSnapshot":
        total = (subtotal - discount_amount) + delivery_fee
        return cls(
            subtotal=subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            discount_amount=discount_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            delivery_fee=delivery_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            total_amount=max(Decimal("0.00"), total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

from typing import Any, Dict, List, Optional
from decimal import Decimal
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log

class PricingService:
    def calculate_price(
        self,
        items: List[Dict[str, Any]],
        order_type: str = "hall",
        delivery_fee: float = 0,
        offer_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate pricing including subtotal, discounts, and total.
        Follows the same logic as the cloud PricingService but uses local data.
        """
        # 1. Calculate raw subtotal from items
        subtotal = sum(item.get("quantity", 0) * item.get("unit_price", 0) for item in items)
        subtotal_dec = Decimal(str(subtotal))
        
        discount_amount = Decimal("0.00")
        
        # 2. Apply Offer if present
        if offer_code:
            offer = local_repository.get_offer_by_code(offer_code)
            if offer:
                now = local_repository.utc_now_iso()
                valid_from = offer.get("valid_from")
                valid_to = offer.get("valid_to")
                
                # Check validity dates
                if (not valid_from or valid_from <= now) and (not valid_to or valid_to >= now):
                    # Check minimum order amount
                    if subtotal_dec >= Decimal(str(offer.get("min_order_amount") or 0)):
                        if offer["discount_type"] == "percentage":
                            discount_amount = subtotal_dec * (Decimal(str(offer["discount_value"])) / Decimal("100"))
                        else:  # fixed
                            discount_amount = Decimal(str(offer["discount_value"]))
                        
                        # Cap discount if max_discount_amount is set
                        max_discount = offer.get("max_discount_amount")
                        if max_discount:
                            discount_amount = min(discount_amount, Decimal(str(max_discount)))
        
        # 3. Handle Delivery Fee
        delivery_fee_dec = Decimal(str(delivery_fee))
        if delivery_fee_dec < 0:
            delivery_fee_dec = Decimal("0.00")
            
        # 4. Consolidate
        total_amount = subtotal_dec - discount_amount + delivery_fee_dec
        if total_amount < 0:
            total_amount = Decimal("0.00")
            
        return {
            "subtotal": float(round(subtotal_dec, 2)),
            "discount_amount": float(round(discount_amount, 2)),
            "delivery_fee": float(round(delivery_fee_dec, 2)),
            "total_amount": float(round(total_amount, 2))
        }

pricing_service = PricingService()

from enum import Enum

class ProductType(str, Enum):
    SIMPLE = "simple"     
    VARIANT = "variant"         

class UserRole(str, Enum):
    ADMIN = "admin"
    CASHIER = "cashier"
    DELIVERY = "delivery"

class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    BUY_ONE_GET_ONE = "buy_one_get_one"
    SEASONAL_DISCOUNT = "seasonal_discount"
    PROMO_CODE = "promo_code"
    BULK_DISCOUNT = "bulk_discount"
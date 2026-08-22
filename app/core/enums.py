from enum import Enum

class CaseInsensitiveEnum(str, Enum):
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return super()._missing_(value)

class ProductType(CaseInsensitiveEnum):
    SIMPLE = "simple"     
    VARIANT = "variant"         

class UserRole(CaseInsensitiveEnum):
    ADMIN = "admin"
    CASHIER = "cashier"
    DELIVERY = "delivery"

class DiscountType(CaseInsensitiveEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    BUY_ONE_GET_ONE = "buy_one_get_one"
    COMBO = "combo"
    BUY_X_GET_Y = "buy_x_get_y"
    QUANTITY_DISCOUNT = "quantity_discount"
    FREE_DELIVERY = "free_delivery"
    CATEGORY_DISCOUNT = "category_discount"
    HAPPY_HOUR = "happy_hour"

class OrderStatus(CaseInsensitiveEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    

class OrderType(CaseInsensitiveEnum):
    HALL = "hall"
    TAKEAWAY = "takeaway"
    DELIVERY = "delivery"
    ONLINE = "online"

class OrderSource(CaseInsensitiveEnum):
    CASHIER = "cashier"
    ONLINE = "online"

class PaymentMethod(CaseInsensitiveEnum):
    CASH = "cash"
    INSTAPAY = "instapay"
    WALLET = "wallet"

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

class OrderStatus(str, Enum):
    NEW = "new"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    

class OrderType(str, Enum):
    HALL = "hall"
    TAKEAWAY = "takeaway"
    DELIVERY = "delivery"
    ONLINE = "online"

class OrderSource(str, Enum):
    CASHIER = "cashier"
    ONLINE = "online"
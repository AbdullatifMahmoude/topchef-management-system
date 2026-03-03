from enum import Enum

class ProductType(str, Enum):
    SIMPLE = "simple"     
    VARIANT = "variant"         

class UserRole(str, Enum):
    ADMIN = "admin"
    CASHIER = "cashier"
    DELIERY= "delivery"
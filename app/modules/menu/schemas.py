from typing import List, Optional, Annotated
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    cat_id: int
    name: str
    price: Decimal = Field(max_digits=10, decimal_places=2)
    is_available: bool

class CreateProduct(ProductBase):
    pass

class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int

class UpdateProduct(BaseModel):
    cat_id: Optional[int] = None
    name: Optional[str] = None
    price: Annotated[Optional[Decimal], Field(max_digits=10, decimal_places=2)] = None


class CategoryBase(BaseModel):
    cat_name: str
    is_active: bool

class CreateCategory(CategoryBase):
    pass

class CategoryResponse(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
   

class UpdateCategory(BaseModel):
    cat_name: Optional[str] = None

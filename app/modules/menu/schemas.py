from typing import List, Optional, Annotated
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from app.core.enums import ProductType


#============== variant ===============#
class VariantBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(max_digits=10, decimal_places=2)

class CreateVariant(VariantBase):
    pass

class UpdateVariant(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    price: Optional[Decimal] = Field(None, max_digits=10, decimal_places=2)

class VariantResponse(VariantBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


#============== product ===============#
class ProductBase(BaseModel):
    cat_id: int
    product_name: str = Field(min_length=2, max_length=255)
    product_type: ProductType
    description: Optional[str] = None
    is_available: bool
    

class CreateProduct(ProductBase):
    variants: List[CreateVariant]
    pass

class ProductResponse(ProductBase):
    id: int
    variants: List[VariantResponse]
    model_config = ConfigDict(from_attributes=True)

class UpdateProduct(BaseModel):
    cat_id: Optional[int] = None
    product_name: Optional[str] = Field(None, min_length=2, max_length=255)
    product_type: Optional[ProductType] = None
    description: Optional[str] = None
    variants: Optional[List[UpdateVariant]] = None





#============== category ===============#
class CategoryBase(BaseModel):
    cat_name: str = Field(min_length=2, max_length=255)

class CreateCategory(CategoryBase):
    pass

class CategoryResponse(CategoryBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
    is_active: bool
   
    
   

class UpdateCategory(BaseModel):
    cat_name: Optional[str] = Field(None, min_length=2, max_length=255)




# #============== addons ===============#
# class CreateAddon(BaseModel):
#     name: str
#     price: Decimal = Field(max_digits=10, decimal_places=2)

# class UpdateAddon(BaseModel):
#     name: Optional[str] = None
#     price: Optional[Decimal] = Field(None, max_digits=10, decimal_places=2)

# class ResponseAddon(CreateAddon):
#     id: int
#     model_config = ConfigDict(from_attributes=True)
    
    



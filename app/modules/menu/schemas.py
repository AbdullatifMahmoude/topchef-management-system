from typing import List, Optional, Annotated
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from app.core.enums import ProductType

# #============== product ===============#
# class ProductBase(BaseModel):
#     cat_id: int
#     name: str
#     product_type: ProductType
#     description: str

# class CreateProduct(ProductBase):
#     pass

# class ProductResponse(ProductBase):
#     id: int
#     model_config = ConfigDict(from_attributes=True)

# class UpdateProduct(BaseModel):
#     cat_id: Optional[int] = None
#     name: Optional[str] = None
#     product_type: ProductType
#     description: Optional[str] = None




# #============== variant ===============#
# class VariantBase(BaseModel):
#     name: str
#     price: Decimal = Field(max_digits=10, decimal_places=2)

# class CreateVariant(VariantBase):
#     pass

# class UpdateVariant(BaseModel):
#     product_id: Optional[int] = None
#     name: Optional[str] = None
#     price: Optional[Decimal] = Field(None, max_digits=10, decimal_places=2)

# class VariantResponse(VariantBase):
#     id: int
#     product_id: int
#     model_config = ConfigDict(from_attributes=True)


#============== category ===============#
class CategoryBase(BaseModel):
    cat_name: str

class CreateCategory(CategoryBase):
    pass

class CategoryResponse(CategoryBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
    is_active: bool
   
    
   

class UpdateCategory(BaseModel):
    cat_name: Optional[str] = None




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
    
    



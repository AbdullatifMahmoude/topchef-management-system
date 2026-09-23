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
    name: str | None = Field(None, min_length=1, max_length=255)
    price: Decimal | None = Field(None, max_digits=10, decimal_places=2)

class VariantResponse(VariantBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


#============== product ===============#
class ProductBase(BaseModel):
    cat_id: int
    product_name: str = Field(min_length=2, max_length=255)
    product_type: ProductType
    description: str | None = None
    is_available: bool
    

class CreateProduct(ProductBase):
    variants: list[CreateVariant]

class ProductResponse(ProductBase):
    id: int
    variants: list[VariantResponse]
    model_config = ConfigDict(from_attributes=True)

class UpdateProduct(BaseModel):
    cat_id: int | None = None
    product_name: str | None = Field(None, min_length=2, max_length=255)
    product_type: ProductType | None = None
    description: str | None = None
    variants: list[UpdateVariant] | None = None





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
    cat_name: str | None = Field(None, min_length=2, max_length=255)




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
    
    



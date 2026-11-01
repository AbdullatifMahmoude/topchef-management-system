from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import UserRole


class CreateUser(BaseModel):
    full_name: str | None = None
    username: Annotated[str, Field(min_length=3, max_length=200)]
    role: UserRole
    phone:Annotated[str, Field(pattern=r"^01[0125][0-9]{8}$")]
    password: Annotated[str, Field(min_length=6, pattern=r"^[A-Za-z0-9]+$")]

class UpdateUser(BaseModel):
    full_name: str | None = None
    username: Annotated[str, Field(min_length=3, max_length=200)] | None= None
    role: UserRole | None = None
    phone: Annotated[str, Field(pattern=r"^01[0125][0-9]{8}$")] | None = None
    password: Annotated[str, Field(min_length=6, pattern=r"^[A-Za-z0-9]+$")] | None = None

class UserResponse(BaseModel):
    id: int
    full_name: str | None = None
    username: str
    role: UserRole
    phone: str
    is_active: bool
    display_name: str | None = None
    
    model_config = ConfigDict(from_attributes=True)
    
    @model_validator(mode='after')
    def set_display_name(self) -> 'UserResponse':
        self.display_name = self.full_name or self.username
        return self


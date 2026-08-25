from pydantic import BaseModel, Field
from typing import Annotated, Optional
from app.core.enums import UserRole


class LoginRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=200)]
    password: Annotated[str, Field(min_length=1)]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: UserRole


class TokenPayload(BaseModel):
    sub: str          # username
    user_id: int
    role: str
    exp: Optional[int] = None

class ForgotPasswordRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=200)]

class ResetPasswordRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=200)]
    code: Annotated[str, Field(pattern=r"^\d{6}$")]
    new_password: Annotated[str, Field(min_length=6, pattern=r"^[A-Za-z0-9]+$")]

class PasswordResetResponse(BaseModel):
    message: str

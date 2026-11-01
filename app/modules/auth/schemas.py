from typing import Annotated

from pydantic import BaseModel, Field

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
    exp: int | None = None

class ForgotPasswordRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=200)]

class ResetPasswordRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=200)]
    challenge_id: Annotated[str, Field(min_length=20, max_length=200)]
    new_password: Annotated[str, Field(min_length=6, pattern=r"^[A-Za-z0-9]+$")]

class PasswordResetResponse(BaseModel):
    message: str

class VerificationChallengeResponse(BaseModel):
    challenge_id: str
    whatsapp_url: str
    expires_in: int

class VerificationStatusResponse(BaseModel):
    verified: bool

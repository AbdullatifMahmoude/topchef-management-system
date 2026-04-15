from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    return await auth_service.login(login_data)

from app.modules.auth.dependencies import get_current_user, security_scheme
from fastapi.security import HTTPAuthorizationCredentials
from app.core.token_blacklist import TokenBlacklist
from app.core.security import decode_token

@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    _current_user = Depends(get_current_user)
):
    """Revoke JWT token (Logout)."""
    token = credentials.credentials
    payload = decode_token(token)
    if payload:
        exp = payload.get("exp")
        await TokenBlacklist().revoke_token(token, exp)
    return {"message": "Logged out successfully"}

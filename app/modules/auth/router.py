from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    PasswordResetResponse,
    ResetPasswordRequest,
    TokenResponse,
    VerificationChallengeResponse,
    VerificationStatusResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/forgot-password", response_model=VerificationChallengeResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
):
    return await AuthService(db, redis=redis).request_password_reset(data.username)

@router.get("/password-reset-status/{challenge_id}", response_model=VerificationStatusResponse)
async def password_reset_status(challenge_id: str, redis=Depends(get_redis)):
    from app.modules.settings.whatsapp_verification import challenge_status
    return VerificationStatusResponse(verified=await challenge_status(redis, challenge_id))

@router.post("/reset-password", response_model=PasswordResetResponse)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    await AuthService(db, redis=redis).reset_password(data.username, data.challenge_id, data.new_password)
    return PasswordResetResponse(message="تم تغيير كلمة المرور بنجاح")


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
):
    auth_service = AuthService(db, redis=redis)
    response = await auth_service.login(login_data)
    
    # Start shift only if the user is a cashier
    from app.core.enums import UserRole
    if response.role == UserRole.CASHIER:
        from app.modules.shifts.service import ShiftsService
        shifts_service = ShiftsService(db, redis)
        await shifts_service.start_shift(response.user_id, sync_web_orders=True)
    
    
    return response

from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions import AuthenticationError, AuthenticationServiceUnavailable
from app.core.security import decode_token
from app.core.token_blacklist import TokenBlacklist
from app.modules.auth.dependencies import get_current_user, security_scheme


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    _current_user = Depends(get_current_user),
    redis = Depends(get_redis),
):
    """Revoke JWT token (Logout)."""
    token = credentials.credentials
    payload = decode_token(token)
    if payload:
        exp = payload.get("exp")
        user_id = payload.get("user_id")
        if not isinstance(exp, int):
            raise AuthenticationError("Token payload is malformed")
        if not await TokenBlacklist().revoke_token(token, exp):
            raise AuthenticationServiceUnavailable()
        
        if user_id:
            from app.core.enums import UserRole
            if payload.get("role") == UserRole.CASHIER.value:
                from app.core.database import AsyncSessionLocal
                from app.modules.shifts.service import ShiftsService
                async with AsyncSessionLocal() as db:
                    shifts_service = ShiftsService(db, redis)
                    await shifts_service.end_shift(user_id, sync_web_orders=True)
    
    return {"message": "Logged out successfully"}

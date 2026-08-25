from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.auth.schemas import LoginRequest, TokenResponse, ForgotPasswordRequest, ResetPasswordRequest, PasswordResetResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/forgot-password", response_model=PasswordResetResponse)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    await AuthService(db).request_password_reset(data.username)
    return PasswordResetResponse(message="إذا كان الحساب موجودًا فسيصل كود التحقق إلى رقم واتساب المسجل")

@router.post("/reset-password", response_model=PasswordResetResponse)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    await AuthService(db).reset_password(data.username, data.code, data.new_password)
    return PasswordResetResponse(message="تم تغيير كلمة المرور بنجاح")


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    response = await auth_service.login(login_data)
    
    # Start shift only if the user is a cashier
    from app.core.enums import UserRole
    if response.role == UserRole.CASHIER:
        from app.modules.shifts.service import ShiftsService
        shifts_service = ShiftsService(db)
        await shifts_service.start_shift(response.user_id)
    
    
    return response

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
        user_id = payload.get("user_id")
        await TokenBlacklist().revoke_token(token, exp)
        
        if user_id:
            from app.core.enums import UserRole
            if payload.get("role") == UserRole.CASHIER.value:
                from app.modules.shifts.service import ShiftsService
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    shifts_service = ShiftsService(db)
                    await shifts_service.end_shift(user_id)
    
    return {"message": "Logged out successfully"}

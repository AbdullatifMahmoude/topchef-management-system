from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cloud_client import cloud_client
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
    response = await auth_service.login(login_data)
    
    # Start shift only if the user is a cashier
    from app.core.enums import UserRole
    if response.role == UserRole.CASHIER:
        from app.modules.shifts.service import ShiftsService
        shifts_service = ShiftsService(db)
        await shifts_service.start_shift(response.user_id)
    
    
    # In desktop mode, make the sync worker immediately authenticate so outbox
    # events (including shift changes) can be pushed right away.
    from app.core.config import settings
    from app.core.events import order_events_manager
    if settings.RUNTIME_MODE == "desktop":
        cloud_client.update_token(response.access_token)
        try:
            import desktop.launcher as desktop_launcher
            desktop_launcher._auth_header_cache = response.access_token if response.access_token.startswith("Bearer ") else f"Bearer {response.access_token}"
        except Exception:
            pass
        await order_events_manager.start()
        
    return response

from app.modules.auth.dependencies import get_current_user, security_scheme
from fastapi.security import HTTPAuthorizationCredentials
from app.core.token_blacklist import TokenBlacklist
from app.core.security import decode_token
from app.core.config import settings
from app.core.events import order_events_manager

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
    
    # In desktop mode, clean up synchronization bridge on logout
    if settings.RUNTIME_MODE == "desktop":
        cloud_client._token = None
        cloud_client._client.headers.pop("Authorization", None)
        try:
            import desktop.launcher as desktop_launcher
            desktop_launcher._auth_header_cache = None
        except Exception:
            pass
        await order_events_manager.stop()
    return {"message": "Logged out successfully"}

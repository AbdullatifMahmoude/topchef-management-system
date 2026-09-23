from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, AuthenticationServiceUnavailable
from app.core.logging import logger
from app.core.redis import get_redis
from app.core.security import decode_token
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenPayload
from app.modules.users.schemas import UserResponse

security_scheme = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    if not credentials:
         raise AuthenticationError("Authorization header missing")
         
    token = credentials.credentials
    
    # ✅ FIX: Check if token is revokedf
    from app.core.token_blacklist import TokenBlacklist
    revocation_status = await TokenBlacklist().is_revoked(token)
    if revocation_status is None:
        raise AuthenticationServiceUnavailable()
    if revocation_status:
        raise AuthenticationError("Token has been revoked. Please log in again.")
        
    payload = decode_token(token)
    if payload is None:
        raise AuthenticationError("Invalid or expired token")

    try:
        token_data = TokenPayload(**payload)
    except Exception:  # noqa: BLE001
        raise AuthenticationError("Token payload is malformed")

    # 1. Try to get user from Redis cache
    cache_key = f"user_session:{token_data.user_id}"
    if redis:
        try:
            cached_user = await redis.get(cache_key)
            if cached_user:
                return UserResponse.model_validate_json(cached_user)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error reading from Redis cache: {e}")

    # 2. If not in cache or error, get from database
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(token_data.user_id)
    if user is None:
        raise AuthenticationError("User no longer exists")

    if not user.is_active:
        raise AuthenticationError("Account has been deactivated")

    # 3. Cache the user for future requests (expire in 10 minutes)
    if redis:
        try:
            user_response = UserResponse.model_validate(user)
            await redis.setex(
                cache_key,
                600,  # 10 minutes
                user_response.model_dump_json()
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error writing to Redis cache: {e}")

    return user

async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
) -> UserResponse | None:
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db, redis)
    except Exception:  # noqa: BLE001
        return None

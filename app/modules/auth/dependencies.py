from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.exceptions import AuthenticationError
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenPayload

security_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
):
    token = credentials.credentials

    payload = decode_token(token)
    if payload is None:
        raise AuthenticationError("Invalid or expired token")

    try:
        token_data = TokenPayload(**payload)
    except Exception:
        raise AuthenticationError("Token payload is malformed")
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(token_data.user_id)

    if user is None:
        raise AuthenticationError("User no longer exists")

    if not user.is_active:
        raise AuthenticationError("Account has been deactivated")

    return user

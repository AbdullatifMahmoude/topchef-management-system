from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password, create_access_token
from app.core.exceptions import AuthenticationError
from app.core.logging import logger
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)

    async def login(self, credentials: LoginRequest) -> TokenResponse:
        user = await self.repo.get_user_by_username(credentials.username)

        if not user:
            logger.warning(f"Login attempt failed: user '{credentials.username}' not found")
            raise AuthenticationError("Invalid username or password")

        if not user.is_active:
            logger.warning(f"Login attempt by inactive user: '{credentials.username}'")
            raise AuthenticationError("Account is deactivated. Contact administrator.")

        if not verify_password(credentials.password, user.hashed_password):
            logger.warning(f"Login attempt failed: wrong password for '{credentials.username}'")
            raise AuthenticationError("Invalid username or password")

        token_data = {
            "sub": user.username,
            "user_id": user.id,
            "role": user.role.value,
        }
        access_token = create_access_token(data=token_data)

        logger.info(f"User '{user.username}' (role={user.role.value}) logged in successfully")

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=user.id,
            username=user.username,
            role=user.role,
        )

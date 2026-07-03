import time
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password, create_access_token
from app.core.exceptions import AuthenticationError
from app.core.logging import logger
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse


# In-memory failed login tracker: { username: { "count": int, "locked_until": float } }
_login_attempts: dict[str, dict] = defaultdict(lambda: {"count": 0, "locked_until": 0.0})
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 300  # 5 minutes


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)

    async def login(self, credentials: LoginRequest) -> TokenResponse:
        username_key = credentials.username.lower()

        # Check if account is temporarily locked
        attempt_info = _login_attempts[username_key]
        if attempt_info["locked_until"] > time.monotonic():
            remaining = int(attempt_info["locked_until"] - time.monotonic())
            logger.warning(f"Login blocked: account '{credentials.username}' is temporarily locked for {remaining}s")
            raise AuthenticationError(
                f"Account temporarily locked due to repeated failed login attempts. Try again in {remaining} seconds."
            )

        user = await self.repo.get_user_by_username(credentials.username)

        if not user:
            logger.warning(f"Login attempt failed: user '{credentials.username}' not found")
            self._record_failed_attempt(username_key)
            raise AuthenticationError("Invalid username or password")

        if not user.is_active:
            logger.warning(f"Login attempt by inactive user: '{credentials.username}'")
            raise AuthenticationError("Account is deactivated. Contact administrator.")

        if not verify_password(credentials.password, user.hashed_password):
            logger.warning(f"Login attempt failed: wrong password for '{credentials.username}'")
            self._record_failed_attempt(username_key)
            raise AuthenticationError("Invalid username or password")

        # Successful login — reset failed attempts
        _login_attempts.pop(username_key, None)

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

    @staticmethod
    def _record_failed_attempt(username_key: str):
        attempt_info = _login_attempts[username_key]
        attempt_info["count"] += 1
        if attempt_info["count"] >= _MAX_FAILED_ATTEMPTS:
            attempt_info["locked_until"] = time.monotonic() + _LOCKOUT_DURATION_SECONDS
            logger.warning(
                "Account '%s' locked for %ds after %d consecutive failed login attempts",
                username_key, _LOCKOUT_DURATION_SECONDS, attempt_info["count"],
            )

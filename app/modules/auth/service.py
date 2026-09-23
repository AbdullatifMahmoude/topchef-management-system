import hashlib
import time
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError
from app.core.logging import logger
from app.core.security import create_access_token, get_password_hash, verify_password
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.settings.whatsapp_verification import (
    consume_verified_challenge,
    create_inbound_challenge,
)
from app.modules.users.repository import UserRepository

# In-memory failed login tracker: { username: { "count": int, "locked_until": float } }
_login_attempts: dict[str, dict] = defaultdict(lambda: {"count": 0, "locked_until": 0.0})
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 300  # 5 minutes
_password_reset_requests: dict[str, float] = {}
_PASSWORD_RESET_COOLDOWN_SECONDS = 60


class AuthService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
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

        logger.info("User login succeeded user_id=%s role=%s", user.id, user.role.value)

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

    async def request_password_reset(self, username: str) -> dict:
        if not await self._allow_password_reset_request(username):
            raise AuthenticationError("انتظر دقيقة قبل إنشاء محاولة تحقق جديدة")
        user = await UserRepository(self.db).get_by_name(username)
        phone = user.phone if user and user.is_active else "01000000000"
        return await create_inbound_challenge(
            self.db, self.redis, phone=phone, actor_type="staff",
            actor_id=user.id if user and user.is_active else None, purpose="reset_password",
        )

    async def _allow_password_reset_request(self, username: str) -> bool:
        username_key = username.lower().strip()
        key_hash = hashlib.sha256(username_key.encode()).hexdigest()
        redis_key = f"auth:password-reset:{key_hash}"
        if self.redis is not None:
            try:
                count = await self.redis.incr(redis_key)
                if count == 1:
                    await self.redis.expire(redis_key, _PASSWORD_RESET_COOLDOWN_SECONDS)
                return count == 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Password reset Redis rate limit unavailable: %s", exc)

        now = time.monotonic()
        expired = [
            key for key, requested_at in _password_reset_requests.items()
            if now - requested_at >= _PASSWORD_RESET_COOLDOWN_SECONDS
        ]
        for key in expired:
            _password_reset_requests.pop(key, None)
        last_request = _password_reset_requests.get(key_hash, 0)
        if now - last_request < _PASSWORD_RESET_COOLDOWN_SECONDS:
            return False
        _password_reset_requests[key_hash] = now
        return True

    async def reset_password(self, username: str, challenge_id: str, new_password: str) -> None:
        user = await UserRepository(self.db).get_by_name(username)
        if not user or not user.is_active:
            raise AuthenticationError("تعذر تأكيد الحساب")
        record = await consume_verified_challenge(
            self.redis, challenge_id, actor_type="staff", purpose="reset_password",
        )
        if record.get("actor_id") != user.id:
            raise AuthenticationError("تعذر تأكيد الحساب")
        user.hashed_password = get_password_hash(new_password)
        _login_attempts.pop(user.username.lower(), None)
        await self.db.flush()

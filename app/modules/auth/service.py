import time
import hashlib
import secrets
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import verify_password, create_access_token
from app.core.exceptions import AuthenticationError
from app.core.logging import logger
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.models import PasswordResetCode
from app.modules.users.repository import UserRepository
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import send_template_text, whatsapp_config_ready
from app.core.config import settings as app_settings
from app.core.security import get_password_hash


# In-memory failed login tracker: { username: { "count": int, "locked_until": float } }
_login_attempts: dict[str, dict] = defaultdict(lambda: {"count": 0, "locked_until": 0.0})
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 300  # 5 minutes
_password_reset_requests: dict[str, float] = {}
_PASSWORD_RESET_COOLDOWN_SECONDS = 60


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

    @staticmethod
    def _reset_code_hash(user_id: int, code: str) -> str:
        value = f"{user_id}:{code}:{app_settings.SECRET_KEY}"
        return hashlib.sha256(value.encode()).hexdigest()

    async def request_password_reset(self, username: str) -> None:
        username_key = username.lower().strip()
        now_monotonic = time.monotonic()
        last_request = _password_reset_requests.get(username_key, 0)
        if now_monotonic - last_request < _PASSWORD_RESET_COOLDOWN_SECONDS:
            return
        _password_reset_requests[username_key] = now_monotonic
        user = await UserRepository(self.db).get_by_name(username)
        # Always return the same public response to prevent account discovery.
        if not user or not user.is_active:
            return
        config = await SettingsService(self.db).get_whatsapp_settings()
        if not whatsapp_config_ready(config, template_name=config.password_reset_template_name):
            logger.info("Password reset skipped: WhatsApp integration is incomplete or disabled")
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = datetime.utcnow()
        previous = await self.db.execute(
            select(PasswordResetCode).where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.is_used == False,
            )
        )
        for reset in previous.scalars().all():
            reset.is_used = True
        self.db.add(PasswordResetCode(
            user_id=user.id,
            code_hash=self._reset_code_hash(user.id, code),
            expires_at=now + timedelta(minutes=config.reset_code_expiry_minutes),
        ))
        await self.db.flush()
        sent = await send_template_text(user.phone, code, config.password_reset_template_name)
        if not sent:
            logger.warning("Password reset WhatsApp was not accepted for user id=%s", user.id)

    async def reset_password(self, username: str, code: str, new_password: str) -> None:
        user = await UserRepository(self.db).get_by_name(username)
        if not user or not user.is_active:
            raise AuthenticationError("كود التحقق غير صحيح أو انتهت صلاحيته")
        result = await self.db.execute(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.is_used == False,
                PasswordResetCode.expires_at >= datetime.utcnow(),
            )
            .order_by(PasswordResetCode.created_at.desc())
        )
        reset = result.scalars().first()
        if not reset or reset.attempts >= 5:
            raise AuthenticationError("كود التحقق غير صحيح أو انتهت صلاحيته")
        reset.attempts += 1
        if not secrets.compare_digest(reset.code_hash, self._reset_code_hash(user.id, code)):
            raise AuthenticationError("كود التحقق غير صحيح أو انتهت صلاحيته")
        user.hashed_password = get_password_hash(new_password)
        reset.is_used = True
        _login_attempts.pop(user.username.lower(), None)
        await self.db.flush()

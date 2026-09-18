import hashlib
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password using bcrypt.
    Includes fallback for legacy SHA256 double-hashed passwords.
    """
    # 1. Try standard bcrypt (Modern)
    try:
        if pwd_context.verify(plain_password, hashed_password):
            return True
    except (TypeError, ValueError):
        return False

    # 2. Try legacy fallback (SHA256 then Bcrypt)
    try:
        legacy_hash = hashlib.sha256(plain_password.encode()).hexdigest()
        if pwd_context.verify(legacy_hash, hashed_password):
            return True
    except (TypeError, ValueError):
        return False

    return False


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt."""
    return pwd_context.hash(password)


def create_access_token(
        data: dict,
        expire_delta: timedelta | None = None) -> str:

    to_encode = data.copy()

    if expire_delta:
        expire = datetime.now(UTC) + expire_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require_exp": True, "require_sub": True},
        )
        if not isinstance(payload.get("user_id"), int) or not payload.get("role"):
            return None
        return payload
    except JWTError:
        return None

from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
import hashlib

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    sha256_hashedpassword = hashlib.sha256(plain_password.encode()).hexdigest()
    return pwd_context.verify(sha256_hashedpassword, hashed_password)


def get_password_hash(password: str) -> str:
    sha256_hashedpassword = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(sha256_hashedpassword)


def create_access_token(
        data: dict,
        expire_delta: Optional[timedelta] = None) -> str:

    to_encode = data.copy()

    if expire_delta:
        expire = datetime.utcnow() + expire_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None

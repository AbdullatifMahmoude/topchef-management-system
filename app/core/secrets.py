import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value or value.startswith(_PREFIX):
        return value
    return _PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith(_PREFIX):
        # Backward-compatible read for values saved before encryption. Saving
        # the settings again migrates them to encrypted storage.
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""

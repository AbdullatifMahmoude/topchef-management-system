from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, decode_token


def test_decode_token_requires_identity_claims():
    missing_user = create_access_token({"sub": "user", "role": "admin"})
    missing_role = create_access_token({"sub": "user", "user_id": 1})
    assert decode_token(missing_user) is None
    assert decode_token(missing_role) is None


def test_decode_token_requires_expiry():
    token = jwt.encode(
        {"sub": "user", "user_id": 1, "role": "admin"},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert decode_token(token) is None

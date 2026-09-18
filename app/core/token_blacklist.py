import hashlib
import time

from redis.exceptions import RedisError

from app.core.logging import logger
from app.core.redis import redis_client


class TokenBlacklist:
    """Manage revoked JWT tokens in the active cache backend."""

    def _token_key(self, token: str) -> str:
        """Return a unique Redis key for a given token using SHA256 hash."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return f"token:revoked:{token_hash}"

    async def revoke_token(self, token: str, exp_timestamp: int) -> bool:
        """Add token to revocation list."""
        try:
            ttl = exp_timestamp - int(time.time())
            if ttl > 0:
                key = self._token_key(token)
                await redis_client.connect()
                await redis_client.setex(key, ttl, "1")
                logger.info("Authentication token revoked")
                return True
        except (RedisError, OSError) as exc:
            logger.warning("Error revoking token: %s", type(exc).__name__)
        return False

    async def is_revoked(self, token: str) -> bool | None:
        """Check if token is revoked."""
        try:
            key = self._token_key(token)
            backend = await redis_client.connect()
            if backend is None:
                return None
            return bool(await backend.exists(key))
        except (RedisError, OSError) as exc:
            logger.warning("Token revocation check unavailable: %s", type(exc).__name__)
            return None

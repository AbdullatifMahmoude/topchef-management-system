import hashlib
from app.core.redis import redis_client
from app.core.logging import logger
import time

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
                logger.info(f"Token revoked: {key}")
                return True
        except Exception as e:
            logger.warning(f"Error revoking token: {e}")
        return False

    async def is_revoked(self, token: str) -> bool:
        """Check if token is revoked."""
        try:
            key = self._token_key(token)
            await redis_client.connect()
            return await redis_client.exists(key)
        except Exception:
            # If the cache backend is unavailable, treat token as valid (fail open)
            return False

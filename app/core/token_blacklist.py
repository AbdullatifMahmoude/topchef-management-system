from app.core.redis import redis_client
from app.core.logging import logger
import time

class TokenBlacklist:
    """Manage revoked JWT tokens in Redis."""
    
    async def revoke_token(self, token: str, exp_timestamp: int) -> bool:
        """Add token to revocation list."""
        try:
            ttl = exp_timestamp - int(time.time())
            if ttl > 0:
                # Store short token hash to minimize memory
                token_hash = token[:30]
                await redis_client.redis.setex(
                    f"token:revoked:{token_hash}",
                    ttl,
                    "1"
                )
                logger.info(f"Token revoked: {token_hash}...")
                return True
        except Exception as e:
            logger.warning(f"Error revoking token: {e}")
        return False
    
    async def is_revoked(self, token: str) -> bool:
        """Check if token is revoked."""
        try:
            token_hash = token[:30]
            exists = await redis_client.redis.exists(f"token:revoked:{token_hash}")
            return bool(exists)
        except Exception:
            return False

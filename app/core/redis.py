from app.core.logging import logger
import redis.asyncio as redis
from app.core.config import settings

class RedisClient:
    def __init__(self):
        self.redis = None

    async def connect(self):
        if not self.redis:
            try:
                self.redis = redis.from_url(
                    settings.REDIS_URL, 
                    decode_responses=True,
                    socket_timeout=5, # Don't hang forever
                    socket_connect_timeout=5
                )
                # Ping to verify connection
                await self.redis.ping()
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. System will proceed without caching.")
                self.redis = None
        return self.redis

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            self.redis = None

redis_client = RedisClient()

async def get_redis():
    return await redis_client.connect()

from app.core.logging import logger
import redis.asyncio as redis
from app.core.config import settings
import time
from typing import Optional, Any

class RedisClient:
    def __init__(self):
        self.redis = None
        # Performance metrics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "avg_response_time": 0.0
        }

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
                logger.info("✓ Redis connected successfully")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. System will proceed without caching.")
                self.redis = None
        return self.redis

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            self.redis = None
            logger.info("✓ Redis disconnected")
    
    async def get(self, key: str, track_hit: bool = True) -> Optional[Any]:
        """Get value with performance tracking."""
        if not self.redis:
            return None
        
        start_time = time.perf_counter()
        try:
            value = await self.redis.get(key)
            elapsed = time.perf_counter() - start_time
            
            if value is not None and track_hit:
                self.stats["hits"] += 1
                logger.debug(f"✓ Cache HIT: {key} ({elapsed*1000:.2f}ms)")
            elif value is None and track_hit:
                self.stats["misses"] += 1
                logger.debug(f"✗ Cache MISS: {key}")
            
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            return value
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Redis GET error for {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set value with performance tracking."""
        if not self.redis:
            return False
        
        start_time = time.perf_counter()
        try:
            await self.redis.set(key, value, ex=ex)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"✓ Cache SET: {key} ({elapsed*1000:.2f}ms)")
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Redis SET error for {key}: {e}")
            return False
    
    async def setex(self, key: str, time: int, value: Any) -> bool:
        """Set value with TTL and performance tracking."""
        if not self.redis:
            return False
        
        start_time = time.perf_counter()
        try:
            await self.redis.setex(key, time, value)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"✓ Cache SETEX: {key} (TTL: {time}s, {elapsed*1000:.2f}ms)")
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Redis SETEX error for {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key with performance tracking."""
        if not self.redis:
            return False
        
        start_time = time.perf_counter()
        try:
            result = await self.redis.delete(key)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"✓ Cache DELETE: {key} ({elapsed*1000:.2f}ms)")
            return result > 0
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Redis DELETE error for {key}: {e}")
            return False
    
    async def incr(self, key: str) -> Optional[int]:
        """Increment counter with performance tracking."""
        if not self.redis:
            return None
        
        start_time = time.perf_counter()
        try:
            result = await self.redis.incr(key)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            return result
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Redis INCR error for {key}: {e}")
            return None
    
    def _update_avg_response_time(self, elapsed: float):
        """Update average response time."""
        total_ops = self.stats["total_operations"]
        if total_ops > 0:
            self.stats["avg_response_time"] = (
                (self.stats["avg_response_time"] * total_ops + elapsed) / (total_ops + 1)
            )
    
    def get_stats(self) -> dict:
        """Get performance statistics."""
        hit_rate = (
            (self.stats["hits"] / (self.stats["hits"] + self.stats["misses"]) * 100)
            if (self.stats["hits"] + self.stats["misses"]) > 0
            else 0
        )
        return {
            **self.stats,
            "hit_rate": f"{hit_rate:.1f}%",
            "avg_response_time_ms": f"{self.stats['avg_response_time']*1000:.2f}"
        }
    
    def reset_stats(self):
        """Reset performance statistics."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "avg_response_time": 0.0
        }

redis_client = RedisClient()

async def get_redis():
    return await redis_client.connect()

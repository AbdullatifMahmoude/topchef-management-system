import time
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import logger


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, Optional[float]]] = {}

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._store.clear()

    def _purge_if_expired(self, key: str) -> None:
        entry = self._store.get(key)
        if not entry:
            return
        _, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            self._store.pop(key, None)

    async def get(self, key: str) -> Optional[Any]:
        self._purge_if_expired(key)
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        expires_at = time.time() + ex if ex else None
        self._store[key] = (value, expires_at)
        return True

    async def setex(self, key: str, ttl_seconds: int, value: Any) -> bool:
        return await self.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> int:
        self._purge_if_expired(key)
        existed = key in self._store
        self._store.pop(key, None)
        return 1 if existed else 0

    async def incr(self, key: str) -> int:
        self._purge_if_expired(key)
        current = self._store.get(key, (0, None))[0]
        new_value = int(current or 0) + 1
        expires_at = self._store.get(key, (None, None))[1]
        self._store[key] = (new_value, expires_at)
        return new_value

    async def exists(self, key: str) -> int:
        self._purge_if_expired(key)
        return 1 if key in self._store else 0


class RedisClient:
    def __init__(self):
        self.redis = None
        self.backend_name = "none"
        self.stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "avg_response_time": 0.0,
        }

    async def connect(self):
        if self.redis:
            return self.redis

        if settings.RUNTIME_MODE == "desktop":
            self.redis = InMemoryCache()
            self.backend_name = "memory"
            logger.info("Desktop mode cache initialized with in-memory backend")
            return self.redis

        try:
            self.redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            await self.redis.ping()
            self.backend_name = "redis"
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. System will proceed without caching.")
            self.redis = None
            self.backend_name = "none"
        return self.redis

    @property
    def is_available(self) -> bool:
        return self.redis is not None

    @property
    def status_label(self) -> str:
        if self.backend_name == "memory":
            return "memory"
        if self.backend_name == "redis" and self.redis is not None:
            return "connected"
        return "disconnected"

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            self.redis = None
            self.backend_name = "none"
            logger.info("Cache backend disconnected")

    async def get(self, key: str, track_hit: bool = True) -> Optional[Any]:
        if not self.redis:
            return None

        start_time = time.perf_counter()
        try:
            value = await self.redis.get(key)
            elapsed = time.perf_counter() - start_time

            if value is not None and track_hit:
                self.stats["hits"] += 1
                logger.debug(f"Cache HIT: {key} ({elapsed*1000:.2f}ms)")
            elif value is None and track_hit:
                self.stats["misses"] += 1
                logger.debug(f"Cache MISS: {key}")

            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            return value
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Cache GET error for {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        if not self.redis:
            return False

        start_time = time.perf_counter()
        try:
            await self.redis.set(key, value, ex=ex)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"Cache SET: {key} ({elapsed*1000:.2f}ms)")
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Cache SET error for {key}: {e}")
            return False

    async def setex(self, key: str, ttl_seconds: int, value: Any) -> bool:
        if not self.redis:
            return False

        start_time = time.perf_counter()
        try:
            await self.redis.setex(key, ttl_seconds, value)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"Cache SETEX: {key} (TTL: {ttl_seconds}s, {elapsed*1000:.2f}ms)")
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Cache SETEX error for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        if not self.redis:
            return False

        start_time = time.perf_counter()
        try:
            result = await self.redis.delete(key)
            elapsed = time.perf_counter() - start_time
            self._update_avg_response_time(elapsed)
            self.stats["total_operations"] += 1
            logger.debug(f"Cache DELETE: {key} ({elapsed*1000:.2f}ms)")
            return result > 0
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Cache DELETE error for {key}: {e}")
            return False

    async def incr(self, key: str) -> Optional[int]:
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
            logger.warning(f"Cache INCR error for {key}: {e}")
            return None

    async def exists(self, key: str) -> bool:
        if not self.redis:
            return False
        try:
            return bool(await self.redis.exists(key))
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"Cache EXISTS error for {key}: {e}")
            return False

    def _update_avg_response_time(self, elapsed: float):
        total_ops = self.stats["total_operations"]
        if total_ops > 0:
            self.stats["avg_response_time"] = (
                (self.stats["avg_response_time"] * total_ops + elapsed) / (total_ops + 1)
            )

    def get_stats(self) -> dict:
        hit_rate = (
            (self.stats["hits"] / (self.stats["hits"] + self.stats["misses"]) * 100)
            if (self.stats["hits"] + self.stats["misses"]) > 0
            else 0
        )
        return {
            **self.stats,
            "backend": self.backend_name,
            "hit_rate": f"{hit_rate:.1f}%",
            "avg_response_time_ms": f"{self.stats['avg_response_time']*1000:.2f}",
        }

    def reset_stats(self):
        self.stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "avg_response_time": 0.0,
        }


redis_client = RedisClient()


async def get_redis():
    return await redis_client.connect()

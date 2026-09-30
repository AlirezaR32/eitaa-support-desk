"""Lightweight rate limiting middleware.

Fixed-window counters keyed by client IP (+ route class). In-memory by default;
when REDIS_URL is set the counters move to Redis so multiple API instances
share limits. No external dependency required for single-node deployments.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings


class _MemoryBackend:
    def __init__(self) -> None:
        self.hits: dict[str, list[int]] = defaultdict(list)

    def hit(self, key: str, window: int, limit: int) -> tuple[int, bool]:
        now = int(time.time())
        recent = [t for t in self.hits[key] if t > now - window]
        recent.append(now)
        self.hits[key] = recent[-(limit + 1) :]
        allowed = len([t for t in recent if t > now - window]) <= limit
        return len(recent), allowed


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self.redis = aioredis.from_url(url, decode_responses=True)

    async def hit(self, key: str, window: int, limit: int) -> tuple[int, bool]:
        pipe = self.redis.pipeline()
        full_key = f"rl:{key}:{window}"
        count = await pipe.incr(full_key)
        if count == 1:
            await pipe.expire(full_key, window)
        await pipe.execute()
        return count, count <= limit


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.memory = _MemoryBackend()
        self.redis = _RedisBackend(settings.redis_url) if settings.redis_url else None

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if not path.startswith(settings.api_prefix):
            return await call_next(request)

        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        is_auth = path.startswith(f"{settings.api_prefix}/auth/login") or path.startswith(
            f"{settings.api_prefix}/auth/refresh"
        )
        limit = settings.rate_limit_auth_per_minute if is_auth else settings.rate_limit_per_minute
        bucket = "auth" if is_auth else "api"

        key = f"{ip}:{bucket}"
        if self.redis is not None:
            count, allowed = await self.redis.hit(key, 60, limit)
        else:
            count, allowed = self.memory.hit(key, 60, limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many requests"}},
                headers={"Retry-After": "60"},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

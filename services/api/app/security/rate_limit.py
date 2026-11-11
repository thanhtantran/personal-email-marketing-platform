"""Fixed-window rate limiting backed by Redis.

Applied to authentication and public endpoints (SPEC.md section 8). Fails open
only if Redis is unreachable is NOT done here: callers decide policy.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.errors import RateLimitedError


async def enforce_rate_limit(
    redis: Redis,
    *,
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    bucket = f"ratelimit:{key}:{window_seconds}"
    count = await redis.incr(bucket)
    if count == 1:
        await redis.expire(bucket, window_seconds)
    if count > limit:
        raise RateLimitedError("Too many requests; please slow down")

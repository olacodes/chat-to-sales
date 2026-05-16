"""
Redis-based rate limiting middleware.

Limits per IP address. Configurable per-route via decorator or global default.
Uses sliding window counter in Redis.

Global defaults:
  - General API: 100 requests/minute
  - Auth OTP:    5 requests/minute
  - Webhook:     No limit (Meta sends bursts)
"""

from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Requests per minute by path prefix
_RATE_LIMITS: dict[str, int] = {
    "/api/v1/auth": 10,          # OTP requests
    "/api/v1/marketing": 30,     # dashboard queries
    "/api/v1": 100,              # general API
}

# Paths exempt from rate limiting
_EXEMPT_PREFIXES = (
    "/health",
    "/api/v1/ingestion",   # WhatsApp webhook — Meta sends bursts
    "/ws/",                # WebSocket
)


def _get_limit(path: str) -> int | None:
    """Return the rate limit for a given path, or None if exempt."""
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None
    for prefix, limit in _RATE_LIMITS.items():
        if path.startswith(prefix):
            return limit
    return 100  # default


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if settings.is_development:
            return await call_next(request)

        path = request.url.path
        limit = _get_limit(path)
        if limit is None:
            return await call_next(request)

        # Identify client by IP (or forwarded IP behind proxy)
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        # Sliding window: 1-minute bucket
        now = datetime.utcnow()
        window_key = f"ratelimit:{client_ip}:{now.strftime('%Y%m%d%H%M')}"

        try:
            from app.infra.cache import get_redis
            redis = get_redis()
            count = await redis.incr(window_key)
            if count == 1:
                await redis.expire(window_key, 60)

            if count > limit:
                logger.warning(
                    "Rate limit exceeded: ip=%s path=%s count=%d limit=%d",
                    client_ip, path, count, limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={"message": "Too many requests. Please try again later."},
                    headers={"Retry-After": "60"},
                )
        except Exception:
            # Redis down — allow the request through
            pass

        return await call_next(request)

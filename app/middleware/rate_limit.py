# app/middleware/rate_limit.py
"""
Rate limiting middleware to prevent abuse and brute force attacks.
Uses in-memory storage for simplicity. For production, use Redis.
"""

import time
import uuid
from typing import Dict, List

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _rid(request: Request) -> str:
    """Get request ID from state or generate one."""
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if rid:
        return str(rid)
    return request.headers.get("x-request-id") or str(uuid.uuid4())


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with different limits for different endpoints.

    Limits:
    - Auth endpoints: 5 requests per minute (prevent brute force)
    - API endpoints: 100 requests per minute per user
    - Public endpoints: 20 requests per minute per IP
    """

    def __init__(self, app):
        super().__init__(app)
        # Format: {key: [(timestamp, timestamp, ...)]}
        self.requests: Dict[str, List[float]] = {}

    def _clean_old_requests(self, key: str, window_seconds: int):
        """Remove requests older than the time window"""
        if key not in self.requests:
            self.requests[key] = []
            return

        cutoff = time.time() - window_seconds
        self.requests[key] = [ts for ts in self.requests[key] if ts > cutoff]

    def _is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check if rate limit is exceeded"""
        self._clean_old_requests(key, window_seconds)

        if len(self.requests[key]) >= max_requests:
            return True

        self.requests[key].append(time.time())
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Get user ID from auth header if available
        user_id = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # For now, use IP. In production, decode JWT to get user_id
            user_id = auth_header[7:20] if len(auth_header) > 20 else None

        # Different rate limits for different endpoints
        if path.startswith("/api/auth/"):
            # Auth endpoints: 5 requests per minute (prevent brute force)
            key = f"auth:{client_ip}"
            if self._is_rate_limited(key, max_requests=5, window_seconds=60):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many authentication attempts. Please try again in 1 minute.",
                            "request_id": _rid(request),
                        }
                    },
                )

        elif path.startswith("/files"):
            # Ingestion endpoints: 30 requests per minute (file uploads/analysis)
            key = f"ingestion:{user_id or client_ip}"
            if self._is_rate_limited(key, max_requests=30, window_seconds=60):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many file operations. Please slow down.",
                            "request_id": _rid(request),
                        }
                    },
                )

        elif path.startswith("/api/"):
            # API endpoints: 300 requests per minute per user/IP (dashboard makes many concurrent calls)
            key = f"api:{user_id or client_ip}"
            if self._is_rate_limited(key, max_requests=300, window_seconds=60):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Rate limit exceeded. Please slow down.",
                            "request_id": _rid(request),
                        }
                    },
                )

        elif path in ["/api/contact/", "/api/newsletter/subscribe"]:
            # Public contact/newsletter: 3 requests per 5 minutes
            key = f"public:{client_ip}"
            if self._is_rate_limited(key, max_requests=3, window_seconds=300):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many requests. Please try again later.",
                            "request_id": _rid(request),
                        }
                    },
                )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = "100"
        response.headers["X-RateLimit-Remaining"] = str(100 - len(self.requests.get(f"api:{user_id or client_ip}", [])))

        return response


class ProductionRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Production-ready rate limiter using Redis.
    Install: pip install redis

    Usage:
        redis_client = redis.Redis(host='localhost', port=6379, db=0)
        app.add_middleware(ProductionRateLimitMiddleware, redis_client=redis_client)
    """

    def __init__(self, app, redis_client=None):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        if not self.redis:
            # Fallback to no rate limiting if Redis not available
            return await call_next(request)

        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Determine rate limit based on endpoint
        if path.startswith("/api/auth/"):
            limit, window = 5, 60
            key = f"ratelimit:auth:{client_ip}"
        elif path.startswith("/api/"):
            limit, window = 100, 60
            auth_header = request.headers.get("authorization", "")
            user_id = auth_header[7:20] if auth_header.startswith("Bearer ") else client_ip
            key = f"ratelimit:api:{user_id}"
        else:
            limit, window = 20, 60
            key = f"ratelimit:public:{client_ip}"

        # Increment counter
        try:
            current = self.redis.incr(key)
            if current == 1:
                self.redis.expire(key, window)

            if current > limit:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": f"Rate limit exceeded. Try again in {window} seconds.",
                            "request_id": _rid(request),
                        }
                    },
                )
        except Exception as e:
            # If Redis fails, allow request (fail open)
            pass

        response = await call_next(request)
        return response

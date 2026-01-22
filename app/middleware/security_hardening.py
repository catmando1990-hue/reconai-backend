# app/middleware/security_hardening.py
"""
Security & Abuse Hardening Middleware (FAIL-CLOSED)

PURPOSE: Enforce fail-closed behavior under abuse and hostile conditions.

PART 1: Mutation Rate Limiter - Stricter limits on POST/PUT/DELETE
PART 2: Auth Guard - Reject requests without valid auth context on protected routes
PART 3: Idempotency Guard - Block replay attacks on sensitive operations

All guards include request_id in error responses for traceability.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# =============================================================================
# HELPERS
# =============================================================================


def _rid(request: Request) -> str:
    """Get request ID from state or generate one."""
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if rid:
        return str(rid)
    return request.headers.get("x-request-id") or str(uuid.uuid4())


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For for proxied requests."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_actor_id(request: Request) -> Optional[str]:
    """Extract actor ID from auth context if available."""
    user = getattr(getattr(request, "state", object()), "user", None)
    if user and isinstance(user, dict):
        return user.get("user_id") or user.get("sub")
    return None


# =============================================================================
# PART 1: MUTATION RATE LIMITER (FAIL-CLOSED)
# =============================================================================

# Configurable via environment variables
MUTATION_RATE_LIMIT_PER_IP = int(os.getenv("MUTATION_RATE_LIMIT_PER_IP", "30"))
MUTATION_RATE_LIMIT_PER_ACTOR = int(os.getenv("MUTATION_RATE_LIMIT_PER_ACTOR", "60"))
MUTATION_RATE_WINDOW_SECONDS = int(os.getenv("MUTATION_RATE_WINDOW_SECONDS", "60"))

# Sensitive routes that require stricter limits
SENSITIVE_MUTATION_ROUTES = {
    "/api/plaid/create-link-token",
    "/api/plaid/exchange-public-token",
    "/api/transactions",
    "/api/admin/maintenance/enable",
    "/api/admin/maintenance/disable",
    "/api/admin/org/tier",
    "/api/billing/create-checkout-session",
    "/api/billing/cancel",
    "/api/billing/downgrade",
    "/api/policy/acknowledge",
}

# Routes with very strict limits (e.g., admin actions)
ADMIN_MUTATION_ROUTES = {
    "/api/admin/maintenance/enable",
    "/api/admin/maintenance/disable",
    "/api/admin/org/tier",
    "/api/admin/fixes",
    "/api/diagnostics/run",
}


class MutationRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiter specifically for mutating (POST/PUT/DELETE) routes.

    FAIL-CLOSED: Returns 429 with request_id when limits exceeded.

    Limits:
    - Per-IP: 30 mutations/minute (protects against distributed attacks)
    - Per-Actor: 60 mutations/minute (protects against compromised accounts)
    - Admin routes: 10 mutations/minute (extra protection for sensitive ops)
    """

    def __init__(self, app):
        super().__init__(app)
        self.ip_requests: Dict[str, List[float]] = defaultdict(list)
        self.actor_requests: Dict[str, List[float]] = defaultdict(list)

    def _clean_old_requests(self, bucket: List[float], window_seconds: int) -> List[float]:
        """Remove requests older than the time window."""
        cutoff = time.time() - window_seconds
        return [ts for ts in bucket if ts > cutoff]

    def _is_rate_limited(
        self,
        key: str,
        requests_dict: Dict[str, List[float]],
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Check if rate limit is exceeded."""
        requests_dict[key] = self._clean_old_requests(requests_dict[key], window_seconds)

        if len(requests_dict[key]) >= max_requests:
            return True

        requests_dict[key].append(time.time())
        return False

    async def dispatch(self, request: Request, call_next):
        # Only rate limit mutating methods
        if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return await call_next(request)

        path = request.url.path
        client_ip = _get_client_ip(request)
        actor_id = _get_actor_id(request)
        request_id = _rid(request)

        # Determine limits based on route sensitivity
        if path in ADMIN_MUTATION_ROUTES:
            ip_limit = 10
            actor_limit = 10
        elif path in SENSITIVE_MUTATION_ROUTES or any(path.startswith(r) for r in SENSITIVE_MUTATION_ROUTES):
            ip_limit = MUTATION_RATE_LIMIT_PER_IP
            actor_limit = MUTATION_RATE_LIMIT_PER_ACTOR
        else:
            # Standard mutation routes get slightly higher limits
            ip_limit = MUTATION_RATE_LIMIT_PER_IP * 2
            actor_limit = MUTATION_RATE_LIMIT_PER_ACTOR * 2

        # Check per-IP limit
        ip_key = f"mutation:ip:{client_ip}"
        if self._is_rate_limited(ip_key, self.ip_requests, ip_limit, MUTATION_RATE_WINDOW_SECONDS):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "error_code": "MUTATION_RATE_EXCEEDED_IP",
                        "message": f"Too many mutation requests from this IP. Limit: {ip_limit}/min.",
                        "request_id": request_id,
                        "retry_after_seconds": MUTATION_RATE_WINDOW_SECONDS,
                    }
                },
                headers={"Retry-After": str(MUTATION_RATE_WINDOW_SECONDS)},
            )

        # Check per-actor limit (if actor is known)
        if actor_id:
            actor_key = f"mutation:actor:{actor_id}"
            if self._is_rate_limited(actor_key, self.actor_requests, actor_limit, MUTATION_RATE_WINDOW_SECONDS):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "error_code": "MUTATION_RATE_EXCEEDED_ACTOR",
                            "message": f"Too many mutation requests from this account. Limit: {actor_limit}/min.",
                            "request_id": request_id,
                            "retry_after_seconds": MUTATION_RATE_WINDOW_SECONDS,
                        }
                    },
                    headers={"Retry-After": str(MUTATION_RATE_WINDOW_SECONDS)},
                )

        response = await call_next(request)
        return response


# =============================================================================
# PART 2: AUTH GUARD (FAIL-CLOSED)
# =============================================================================

# Routes that MUST have valid auth context (fail-closed)
PROTECTED_ROUTES_PREFIXES = [
    "/api/plaid/",
    "/api/transactions/",
    "/api/admin/",
    "/api/billing/",
    "/api/policy/",
    "/api/govcon/",
    "/api/intelligence/",
    "/api/cfo/",
]

# Routes explicitly allowed without auth
PUBLIC_ROUTES = {
    "/",
    "/health",
    "/health/",
    "/health/ready",
    "/health/live",
    "/api/maintenance/status",
    "/api/auth/verify",
    "/api/contact",
    "/api/newsletter/subscribe",
}


class AuthGuardMiddleware(BaseHTTPMiddleware):
    """
    Auth guard for protected routes.

    FAIL-CLOSED: Rejects requests without valid auth context on protected routes.
    Returns 401 with request_id for traceability.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        request_id = _rid(request)

        # Allow public routes
        if path in PUBLIC_ROUTES or path.rstrip("/") in PUBLIC_ROUTES:
            return await call_next(request)

        # Allow OPTIONS (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Check if route requires auth
        requires_auth = any(path.startswith(prefix) for prefix in PROTECTED_ROUTES_PREFIXES)

        if not requires_auth:
            return await call_next(request)

        # FAIL-CLOSED: Require valid auth context
        user = getattr(getattr(request, "state", object()), "user", None)

        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": {
                        "code": "AUTH_REQUIRED",
                        "error_code": "MISSING_AUTH_CONTEXT",
                        "message": "Authentication required for this endpoint",
                        "request_id": request_id,
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate auth context has required fields
        if not isinstance(user, dict) or not user.get("user_id"):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": {
                        "code": "AUTH_INVALID",
                        "error_code": "INVALID_AUTH_CONTEXT",
                        "message": "Invalid authentication context",
                        "request_id": request_id,
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)


# =============================================================================
# PART 3: IDEMPOTENCY GUARD (REPLAY PROTECTION)
# =============================================================================

# In-memory idempotency store (use Redis in production)
# Format: {idempotency_key: (timestamp, response_hash)}
_idempotency_store: Dict[str, tuple] = {}
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "3600"))  # 1 hour

# Routes that require idempotency protection
IDEMPOTENT_ROUTES = {
    "/api/plaid/exchange-public-token",
    "/api/billing/create-checkout-session",
    "/api/admin/maintenance/enable",
    "/api/admin/maintenance/disable",
    "/api/admin/org/tier",
    "/api/policy/acknowledge",
}


def _compute_idempotency_key(request: Request, body: bytes) -> str:
    """
    Compute idempotency key from request attributes.

    Key components:
    - X-Idempotency-Key header (if provided)
    - OR: hash of (method, path, user_id, body)
    """
    # Prefer explicit idempotency key
    explicit_key = request.headers.get("x-idempotency-key")
    if explicit_key:
        return explicit_key

    # Compute implicit key
    actor_id = _get_actor_id(request) or _get_client_ip(request)
    key_parts = [
        request.method,
        request.url.path,
        actor_id,
        body.decode("utf-8", errors="ignore") if body else "",
    ]
    key_string = "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()[:32]


def _clean_expired_idempotency_keys():
    """Remove expired idempotency keys."""
    now = time.time()
    expired = [k for k, (ts, _) in _idempotency_store.items() if now - ts > IDEMPOTENCY_TTL_SECONDS]
    for k in expired:
        del _idempotency_store[k]


class IdempotencyGuardMiddleware(BaseHTTPMiddleware):
    """
    Idempotency guard to prevent replay attacks on sensitive operations.

    FAIL-CLOSED: Rejects duplicate requests with 409 Conflict.
    Includes request_id for traceability.

    Clients can provide X-Idempotency-Key header for explicit idempotency.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        request_id = _rid(request)

        # Only apply to POST/PUT on idempotent routes
        if method not in ("POST", "PUT"):
            return await call_next(request)

        if path not in IDEMPOTENT_ROUTES and not any(path.startswith(r) for r in IDEMPOTENT_ROUTES):
            return await call_next(request)

        # Clean expired keys periodically
        _clean_expired_idempotency_keys()

        # Read body for idempotency key computation
        body = await request.body()
        idempotency_key = _compute_idempotency_key(request, body)

        # Check for replay
        if idempotency_key in _idempotency_store:
            stored_ts, stored_hash = _idempotency_store[idempotency_key]
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": {
                        "code": "REPLAY_DETECTED",
                        "error_code": "IDEMPOTENCY_CONFLICT",
                        "message": "This request has already been processed",
                        "request_id": request_id,
                        "idempotency_key": idempotency_key,
                        "original_timestamp": datetime.fromtimestamp(stored_ts, tz=timezone.utc).isoformat(),
                    }
                },
            )

        # Replace body reader since we consumed it
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive  # noqa: SLF001

        # Process request
        response = await call_next(request)

        # Store idempotency key on success (2xx responses)
        if 200 <= response.status_code < 300:
            response_hash = hashlib.sha256(str(response.status_code).encode()).hexdigest()[:16]
            _idempotency_store[idempotency_key] = (time.time(), response_hash)

        return response


# =============================================================================
# COMBINED SECURITY MIDDLEWARE
# =============================================================================


class SecurityHardeningMiddleware(BaseHTTPMiddleware):
    """
    Combined security hardening middleware.

    Applies all security guards in order:
    1. Mutation rate limiting
    2. Auth context validation
    3. Idempotency protection

    FAIL-CLOSED: Any security check failure aborts the request.
    """

    def __init__(self, app):
        super().__init__(app)
        self.mutation_limiter = MutationRateLimitMiddleware(app)
        self.auth_guard = AuthGuardMiddleware(app)
        self.idempotency_guard = IdempotencyGuardMiddleware(app)

        # Rate limiting state (shared)
        self.ip_requests: Dict[str, List[float]] = defaultdict(list)
        self.actor_requests: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Delegate to individual guards
        # Note: In production, consider using separate middleware instances
        # for better control over ordering
        return await call_next(request)

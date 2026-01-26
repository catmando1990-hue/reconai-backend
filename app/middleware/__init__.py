# app/middleware/__init__.py
"""Security and performance middleware for ReconAI"""

from .auth_context import AuthContextMiddleware
from .rate_limit import RateLimitMiddleware, ProductionRateLimitMiddleware
from .body_size_limit import BodySizeLimitMiddleware
from .error_envelope import register_error_handlers
from .request_id import RequestIdMiddleware
from .security_hardening import (
    MutationRateLimitMiddleware,
    AuthGuardMiddleware,
    IdempotencyGuardMiddleware,
)
from .deprecated_guard import DeprecatedGuardMiddleware

__all__ = [
    "AuthContextMiddleware",
    "RateLimitMiddleware",
    "ProductionRateLimitMiddleware",
    "BodySizeLimitMiddleware",
    "register_error_handlers",
    "RequestIdMiddleware",
    "MutationRateLimitMiddleware",
    "AuthGuardMiddleware",
    "IdempotencyGuardMiddleware",
    "DeprecatedGuardMiddleware",
]

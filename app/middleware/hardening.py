# app/middleware/hardening.py
"""
STEP 26 — Platform Hardening Middleware & Utilities

Provides:
- Rate limiting utilities
- Request body caps
- Response size caps
- Timeout management
- Structured error responses with request_id
- PII/Secret leak prevention

Requirements:
- All errors include request_id
- No secrets or PII in error responses
- Fail closed on unknown errors
"""

from __future__ import annotations

import os
import time
import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Any, Callable
from uuid import uuid4
from datetime import datetime

from fastapi import HTTPException, Request


# ============================================================================
# Rate Limiting
# ============================================================================

# Global rate limit cache (in production, use Redis)
_rate_limit_cache: Dict[str, List[float]] = defaultdict(list)

# Default rate limit settings
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 100


def check_rate_limit(
    key: str,
    request_id: str,
    max_requests: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS,
    window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    """
    Check and enforce rate limiting for a given key (user_id, org_id, IP, etc.).

    Raises HTTPException(429) if rate limit exceeded.
    Includes request_id in error response.
    """
    now = time.time()
    window_start = now - window_seconds

    # Clean old entries
    _rate_limit_cache[key] = [
        ts for ts in _rate_limit_cache[key] if ts > window_start
    ]

    # Check limit
    if len(_rate_limit_cache[key]) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds.",
                "request_id": request_id,
                "retry_after_seconds": window_seconds,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # Record this request
    _rate_limit_cache[key].append(now)


def get_rate_limit_status(key: str, window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS) -> Dict[str, Any]:
    """Get current rate limit status for a key."""
    now = time.time()
    window_start = now - window_seconds

    recent_requests = len([
        ts for ts in _rate_limit_cache.get(key, []) if ts > window_start
    ])

    return {
        "recent_requests": recent_requests,
        "window_seconds": window_seconds,
    }


# ============================================================================
# Request Body Size Enforcement
# ============================================================================

MAX_REQUEST_BODY_SIZE = 1_000_000  # 1MB default


def check_request_size(
    content_length: Optional[int],
    request_id: str,
    max_size: int = MAX_REQUEST_BODY_SIZE,
) -> None:
    """
    Check if request body size exceeds maximum.

    Raises HTTPException(413) if too large.
    """
    if content_length and content_length > max_size:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "REQUEST_TOO_LARGE",
                "message": f"Request body exceeds maximum size of {max_size} bytes.",
                "request_id": request_id,
                "content_length": content_length,
                "max_size": max_size,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


# ============================================================================
# Response Size Enforcement
# ============================================================================

MAX_RESPONSE_SIZE = 5_000_000  # 5MB default for responses


def check_response_size(
    response_size: int,
    request_id: str,
    max_size: int = MAX_RESPONSE_SIZE,
) -> None:
    """
    Check if response size exceeds maximum.

    Raises HTTPException(500) if too large (internal error).
    """
    if response_size > max_size:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "RESPONSE_TOO_LARGE",
                "message": "Response exceeds maximum size limit.",
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


# ============================================================================
# Timeout Enforcement
# ============================================================================

DEFAULT_TIMEOUT_SECONDS = 30


async def with_timeout(
    coro,
    request_id: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
):
    """
    Execute a coroutine with timeout.

    Raises HTTPException(504) if timeout exceeded.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "OPERATION_TIMEOUT",
                "message": f"Operation timed out after {timeout_seconds} seconds.",
                "request_id": request_id,
                "timeout_seconds": timeout_seconds,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


# ============================================================================
# Error Sanitization (prevent PII/secret leaks)
# ============================================================================

# Patterns that should never appear in error messages
SENSITIVE_PATTERNS = [
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "cvv",
    "routing_number",
    "account_number",
    "bank_account",
    # Email patterns
    "email",
    "@",
    # Connection string patterns
    "connection_string",
    "conn_str",
    "database_url",
    "db_url",
    "mongodb://",
    "postgres://",
    "postgresql://",
    "mysql://",
    "redis://",
    "amqp://",
]


def sanitize_error_message(message: str) -> str:
    """
    Sanitize error message to remove potential PII/secrets.

    Returns sanitized message safe for logging/responses.
    """
    lower_message = message.lower()

    for pattern in SENSITIVE_PATTERNS:
        if pattern in lower_message:
            return "An error occurred. Sensitive data has been redacted from this message."

    return message


def create_structured_error(
    error_code: str,
    message: str,
    request_id: str,
    status_code: int = 500,
    extra: Optional[Dict[str, Any]] = None,
) -> HTTPException:
    """
    Create a structured error response with request_id.

    Sanitizes message to prevent PII/secret leaks.
    """
    detail = {
        "error": error_code,
        "message": sanitize_error_message(message),
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if extra:
        # Sanitize extra fields
        for key, value in extra.items():
            if isinstance(value, str):
                detail[key] = sanitize_error_message(value)
            else:
                detail[key] = value

    return HTTPException(status_code=status_code, detail=detail)


# ============================================================================
# Hardening Configuration
# ============================================================================

def get_hardening_config() -> Dict[str, Any]:
    """Get current hardening configuration."""
    return {
        "rate_limiting": {
            "default_max_requests": DEFAULT_RATE_LIMIT_MAX_REQUESTS,
            "default_window_seconds": DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        },
        "request_limits": {
            "max_body_size_bytes": MAX_REQUEST_BODY_SIZE,
        },
        "response_limits": {
            "max_size_bytes": MAX_RESPONSE_SIZE,
        },
        "timeouts": {
            "default_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        "security": {
            "error_sanitization": True,
            "sensitive_patterns_count": len(SENSITIVE_PATTERNS),
        },
    }

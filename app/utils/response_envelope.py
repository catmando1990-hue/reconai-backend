"""
Response Envelope Utility — Phase 5 Diagnostics JSON Hardening

Provides structured JSON response helpers that ALWAYS return a consistent envelope:
{
    "request_id": string,
    "timestamp": ISO8601,
    "status": "ok" | "error",
    "data": object | null,
    "error": object | null
}

Usage:
    from app.utils.response_envelope import ok, error, envelope_exception_handler

    @router.get("/endpoint")
    async def endpoint():
        return ok({"key": "value"}, request_id)

    @router.get("/error")
    async def error_endpoint():
        return error("Something went wrong", request_id, status_code=500)
"""

from datetime import datetime
from typing import Any, Optional
from fastapi.responses import JSONResponse
import uuid


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return str(uuid.uuid4())


def ok(
    data: Any,
    request_id: Optional[str] = None,
    status_code: int = 200,
) -> JSONResponse:
    """
    Return a successful JSON envelope response.

    Args:
        data: The response data payload
        request_id: Optional request ID (generated if not provided)
        status_code: HTTP status code (default 200)

    Returns:
        JSONResponse with structured envelope
    """
    if request_id is None:
        request_id = generate_request_id()

    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "ok",
            "data": data,
            "error": None,
        },
        media_type="application/json",
    )


def error(
    message: str,
    request_id: Optional[str] = None,
    status_code: int = 500,
    details: Optional[dict] = None,
) -> JSONResponse:
    """
    Return an error JSON envelope response.

    Args:
        message: Human-readable error message
        request_id: Optional request ID (generated if not provided)
        status_code: HTTP status code (default 500)
        details: Optional additional error details

    Returns:
        JSONResponse with structured error envelope
    """
    if request_id is None:
        request_id = generate_request_id()

    error_payload = {
        "message": message,
        "code": status_code,
    }

    if details:
        error_payload["details"] = details

    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "error",
            "data": None,
            "error": error_payload,
        },
        media_type="application/json",
    )


def wrap_data(
    data: Any,
    request_id: Optional[str] = None,
) -> dict:
    """
    Wrap data in envelope structure (for use with existing return patterns).

    Returns dict instead of JSONResponse for flexibility.
    """
    if request_id is None:
        request_id = generate_request_id()

    return {
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "ok",
        "data": data,
        "error": None,
    }


def wrap_error(
    message: str,
    request_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    """
    Wrap error in envelope structure (for use with existing return patterns).

    Returns dict instead of JSONResponse for flexibility.
    """
    if request_id is None:
        request_id = generate_request_id()

    error_payload = {"message": message}
    if details:
        error_payload["details"] = details

    return {
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "error",
        "data": None,
        "error": error_payload,
    }

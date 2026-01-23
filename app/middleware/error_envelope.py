# BUILD 14 — Structured error envelopes (FastAPI)
# Mount with register_error_handlers(app). Requires RequestIdMiddleware OR falls back to header/uuid.
#
# All error responses include x-request-id header for traceability.

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.middleware.request_id import get_request_id


def _rid(request: Request) -> str:
    """Get request_id from request state, context var, header, or generate new."""
    # Try request.state first (set by middleware via scope["state"])
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if rid:
        return str(rid)
    # Try context var (set by ASGI middleware)
    ctx_rid = get_request_id()
    if ctx_rid:
        return ctx_rid
    # Fallback to header or generate
    return request.headers.get("x-request-id") or str(uuid.uuid4())


def _env(code: str, message: str, request_id: str, extra: Dict[str, Any] | None = None):
    body: Dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id}}
    if extra:
        body["error"].update(extra)
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = _rid(request)
        headers = {"x-request-id": request_id}

        # If existing code uses detail={"error": "...", "message": "..."}, map it.
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("error") or "HTTP_ERROR")
            message = str(exc.detail.get("message") or "Request failed")
            return JSONResponse(
                status_code=exc.status_code,
                content=_env(code, message, request_id),
                headers=headers,
            )

        # If detail is a CODE-like string, treat as code.
        if isinstance(exc.detail, str) and exc.detail.isupper() and " " not in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=_env(exc.detail, "Request failed", request_id),
                headers=headers,
            )

        message = str(exc.detail) if exc.detail is not None else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=_env("HTTP_ERROR", message, request_id),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = _rid(request)
        headers = {"x-request-id": request_id}
        fields = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_env("VALIDATION_ERROR", "Validation failed", request_id, {"fields": fields}),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = _rid(request)
        headers = {"x-request-id": request_id}
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=_env("INTERNAL_ERROR", "Internal server error", request_id),
            headers=headers,
        )

# BUILD 14 — Structured error envelopes (FastAPI)
# Mount with register_error_handlers(app). Requires RequestIdMiddleware OR falls back to header/uuid.

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


def _rid(request: Request) -> str:
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if rid:
        return str(rid)
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

        # If existing code uses detail={"error": "...", "message": "..."}, map it.
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("error") or "HTTP_ERROR")
            message = str(exc.detail.get("message") or "Request failed")
            return JSONResponse(status_code=exc.status_code, content=_env(code, message, request_id))

        # If detail is a CODE-like string, treat as code.
        if isinstance(exc.detail, str) and exc.detail.isupper() and " " not in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=_env(exc.detail, "Request failed", request_id))

        message = str(exc.detail) if exc.detail is not None else "Request failed"
        return JSONResponse(status_code=exc.status_code, content=_env("HTTP_ERROR", message, request_id))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = _rid(request)
        fields = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_env("VALIDATION_ERROR", "Validation failed", request_id, {"fields": fields}),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = _rid(request)
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=_env("INTERNAL_ERROR", "Internal server error", request_id),
        )

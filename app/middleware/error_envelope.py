# BUILD 12E — Structured Error Envelopes (FastAPI)
# Drop-in utilities. Caller mounts via register_error_handlers(app).

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


def _req_id(request: Request) -> str:
    rid = request.headers.get("x-request-id")
    return rid or str(uuid.uuid4())


def _envelope(code: str, message: str, request_id: str, extra: Dict[str, Any] | None = None):
    body: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if extra:
        body["error"].update(extra)
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = _req_id(request)
        code = "HTTP_ERROR"
        # If detail is already a code-like string, pass it through as code.
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        if isinstance(exc.detail, str) and exc.detail.isupper() and " " not in exc.detail:
            code = exc.detail
            message = "Request failed"
        else:
            message = detail
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, message, request_id))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = _req_id(request)
        fields = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", "Validation failed", request_id, {"fields": fields}),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = _req_id(request)
        # Do not leak internals
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("INTERNAL_ERROR", "Internal server error", request_id),
        )

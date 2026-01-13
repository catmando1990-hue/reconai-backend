# BUILD 14 — Body size cap middleware (FastAPI/Starlette)
# app.add_middleware(BodySizeLimitMiddleware, max_bytes=...)
# Includes request_id in error envelope for traceability.

from __future__ import annotations

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_MAX_BYTES = 1_000_000  # 1MB


def _rid(request: Request) -> str:
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if rid:
        return str(rid)
    return request.headers.get("x-request-id") or str(uuid.uuid4())


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = DEFAULT_MAX_BYTES):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": "Request body too large",
                                "request_id": _rid(request),
                            }
                        },
                    )
            except ValueError:
                pass

        body = await request.body()
        if len(body) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Request body too large",
                        "request_id": _rid(request),
                    }
                },
            )

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # noqa: SLF001
        return await call_next(request)

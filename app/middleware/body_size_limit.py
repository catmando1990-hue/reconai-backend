# BUILD 12E — Request Size Caps (FastAPI / Starlette middleware)
# Mount as middleware: app.add_middleware(BodySizeLimitMiddleware, max_bytes=...)
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_MAX_BYTES = 1_000_000  # 1MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = DEFAULT_MAX_BYTES):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # Skip GET/HEAD and websocket-like traffic.
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
                            }
                        },
                    )
            except ValueError:
                pass

        # If no content-length, we still need to cap reads.
        body = await request.body()
        if len(body) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Request body too large",
                    }
                },
            )

        # Re-inject body for downstream consumers
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # noqa: SLF001 (Starlette internal)
        return await call_next(request)

# BUILD 14 — Request ID middleware (FastAPI)
# Adds/propagates X-Request-Id and stores it on request.state.request_id
#
# Uses raw ASGI middleware pattern to guarantee x-request-id header on ALL responses:
# - 200 OK responses
# - HTTPException responses (4xx, 5xx)
# - Unhandled exception responses
# - OPTIONS/CORS preflight responses

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Context variable to propagate request_id across async contexts
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdMiddleware:
    """
    Raw ASGI middleware that guarantees x-request-id header on every response.

    Unlike BaseHTTPMiddleware, this properly handles:
    - Exception handler responses (HTTPException, validation errors)
    - Unhandled exceptions caught by Starlette
    - Streaming responses
    - WebSocket connections (passes through unchanged)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass through WebSocket and lifespan events unchanged
            await self.app(scope, receive, send)
            return

        # Extract or generate request_id
        headers = dict(scope.get("headers", []))
        rid = headers.get(b"x-request-id", b"").decode("utf-8") or str(uuid.uuid4())

        # Store in context var for access in exception handlers
        request_id_ctx.set(rid)

        # Store on scope for access via request.state.request_id
        # Starlette's Request object reads from scope["state"]
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = rid

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Inject x-request-id header into response
                headers = list(message.get("headers", []))
                # Remove any existing x-request-id header (case-insensitive)
                headers = [(k, v) for k, v in headers if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode("utf-8")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def get_request_id() -> str:
    """Get current request_id from context (for use in exception handlers)."""
    return request_id_ctx.get() or str(uuid.uuid4())

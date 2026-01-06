from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth_context import get_current_context, get_current_identity, get_org_service


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Populate request.state.user when a valid Bearer token is present.

    This keeps routes free to use either dependency-based auth or request.state.
    Public routes still work without Authorization.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.user = None

        auth_header = request.headers.get("authorization")
        if auth_header:
            try:
                service = get_org_service()
                identity = await get_current_identity(authorization=auth_header, service=service)
                ctx = await get_current_context(identity=identity, service=service)
                request.state.user = ctx
            except Exception:
                # Don't block public routes; protected routes will enforce auth via dependencies
                request.state.user = None

        return await call_next(request)

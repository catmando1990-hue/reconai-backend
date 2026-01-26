# app/middleware/deprecated_guard.py
"""
Deprecated Endpoint Guard Middleware

PURPOSE:
Returns HTTP 410 Gone for deprecated endpoints identified in the
Backend Endpoint Coverage Audit.

CANONICAL LAWS:
- Fail-closed: Unknown paths pass through (not blocked)
- No auth bypass: Does not modify auth state
- No business logic: Pure routing guard only

DEPRECATED ENDPOINTS (from audit):
- /api/auth/session - Superseded by /api/auth/me
- /api/auth/debug/* - Dev-only, security risk
- /api/readonly/* - Duplicates main endpoints
- /mvp/* - Demo mode only, unused
- /api/evidence/items - Superseded by /govcon/evidence
- /cfo/export - No UI, orphaned
- /api/export-pack/request - Superseded by evidence_export

RESPONSE FORMAT:
All deprecated endpoints return:
- Status: 410 Gone
- Headers: X-Request-Id, Deprecation, Sunset
- Body: Structured JSON with migration guidance
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.requests import Request
from uuid import uuid4


class DeprecatedGuardMiddleware(BaseHTTPMiddleware):
    """
    Middleware that returns 410 Gone for deprecated endpoints.

    FAIL-CLOSED: Only explicitly deprecated paths are blocked.
    All other paths pass through unchanged.
    """

    # Exact path matches - return 410
    DEPRECATED_EXACT: set[str] = {
        "/api/auth/session",
        "/api/evidence/items",
        "/cfo/export",
        "/api/export-pack/request",
    }

    # Prefix matches - return 410 for any path starting with these
    DEPRECATED_PREFIXES: list[str] = [
        "/api/auth/debug",
        "/api/readonly",
        "/mvp",
    ]

    # Migration guidance for deprecated endpoints
    MIGRATION_GUIDANCE: dict[str, str] = {
        "/api/auth/session": "Use GET /api/auth/me instead",
        "/api/auth/debug": "Debug endpoints removed for security. Use /api/me/claims for token inspection.",
        "/api/readonly": "Use the primary endpoints without /readonly prefix",
        "/mvp": "MVP demo endpoints removed. Use production endpoints.",
        "/api/evidence/items": "Use GET /govcon/evidence instead",
        "/cfo/export": "Use /api/exports/csv or /api/exports/json instead",
        "/api/export-pack/request": "Use /api/evidence/export/generate instead",
    }

    # Sunset date for deprecated endpoints (ISO 8601)
    SUNSET_DATE = "2025-06-01T00:00:00Z"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Check if path is deprecated
        is_deprecated, migration_hint = self._check_deprecated(path)

        if is_deprecated:
            # Get or generate request_id for traceability
            request_id = getattr(request.state, "request_id", None) or str(uuid4())

            return JSONResponse(
                status_code=410,
                content={
                    "error": "ENDPOINT_DEPRECATED",
                    "message": f"This endpoint has been deprecated and removed.",
                    "path": path,
                    "migration": migration_hint,
                    "documentation": "https://docs.reconai.com/api/migration",
                    "request_id": request_id,
                },
                headers={
                    "X-Request-Id": request_id,
                    "Deprecation": "true",
                    "Sunset": self.SUNSET_DATE,
                    "Link": '<https://docs.reconai.com/api/migration>; rel="deprecation"',
                },
            )

        # Pass through for non-deprecated endpoints
        return await call_next(request)

    def _check_deprecated(self, path: str) -> tuple[bool, str]:
        """
        Check if a path is deprecated.

        Returns (is_deprecated, migration_guidance).

        FAIL-CLOSED: Only explicitly listed paths are blocked.
        """
        # Check exact matches first
        if path in self.DEPRECATED_EXACT:
            guidance = self.MIGRATION_GUIDANCE.get(path, "See API documentation for alternatives.")
            return True, guidance

        # Check prefix matches
        for prefix in self.DEPRECATED_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                guidance = self.MIGRATION_GUIDANCE.get(prefix, "See API documentation for alternatives.")
                return True, guidance

        # Not deprecated - pass through
        return False, ""

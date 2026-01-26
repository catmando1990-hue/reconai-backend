# app/middleware/incident_guard.py
"""
Incident Mode Guard Middleware (Step 16)

Blocks all non-admin requests when system is in incident mode.
Allows /system/* and /health/* endpoints to pass through.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.db import DB_PATH


class IncidentGuardMiddleware(BaseHTTPMiddleware):
    """
    Middleware that blocks requests when incident mode is active.

    Allows through:
    - /system/* endpoints (for admin control)
    - /health/* endpoints (for monitoring)
    - / root endpoint (for basic health check)
    - OPTIONS requests (for CORS preflight)
    """

    # Paths that are always allowed, even in incident mode
    ALLOWED_PATHS = (
        "/system",
        "/health",
        "/",
    )

    async def dispatch(self, request: Request, call_next: Callable):
        # Always allow OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check if path is allowed
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in self.ALLOWED_PATHS):
            return await call_next(request)

        # Check incident mode status
        # P1 FIX: FAIL-CLOSED - block requests if we can't determine status
        try:
            incident_mode = self._check_incident_mode()
        except Exception as e:
            # P1 FIX: FAIL-CLOSED - if we can't check, block the request
            # This is the secure default per canonical laws
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "SERVICE_UNAVAILABLE",
                    "message": "ReconAI incident mode status could not be determined. Failing closed for safety.",
                    "incident_mode": True,
                    "fail_closed": True,
                    "canonical_law": "fail_closed_on_uncertainty"
                }
            )

        if incident_mode:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "SERVICE_UNAVAILABLE",
                    "message": "ReconAI is currently in maintenance/incident mode. Please try again later.",
                    "incident_mode": True
                }
            )

        return await call_next(request)

    def _check_incident_mode(self) -> bool:
        """
        Check if incident mode is active.

        P1 FIX: FAIL-CLOSED - raises exception on DB errors
        so caller can handle with fail-closed behavior.
        """
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT incident_mode FROM system_state WHERE id = 1")
                row = cursor.fetchone()

                if row:
                    return bool(row["incident_mode"])
                # P1 FIX: If no system_state row exists, fail closed (assume incident mode)
                # This prevents bypass if system_state table is empty/missing
                return True
        except sqlite3.Error as e:
            # P1 FIX: FAIL-CLOSED - re-raise so dispatch() handles with 503
            # Do NOT return False (fail-open) on database errors
            raise RuntimeError(f"Cannot determine incident mode status: {e}") from e

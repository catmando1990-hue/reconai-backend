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
        try:
            incident_mode = self._check_incident_mode()
        except Exception:
            # If we can't check, allow request through
            return await call_next(request)

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
        """Check if incident mode is active."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT incident_mode FROM system_state WHERE id = 1")
                row = cursor.fetchone()

                if row:
                    return bool(row["incident_mode"])
                return False
        except sqlite3.Error:
            return False

"""
Admin Diagnostics API — Phase 5 JSON Envelope Hardening

Wraps admin diagnostic endpoints to ALWAYS return structured JSON envelope.
Never returns empty bodies or non-JSON responses.

Envelope format:
{
    "request_id": string,
    "timestamp": ISO8601,
    "status": "ok" | "error",
    "data": object | null,
    "error": object | null
}
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Literal
from datetime import datetime
import traceback

from app.auth_context import get_current_context, AuthContext
from app.utils.response_envelope import (
    ok,
    error,
    generate_request_id,
    wrap_data,
    wrap_error,
)

router = APIRouter(prefix="/api/admin/diagnostics", tags=["Admin Diagnostics (Envelope)"])


def _assert_admin(ctx: AuthContext):
    """Ensure the user has admin privileges."""
    clerk_metadata = ctx.get("clerk_metadata") or {}
    clerk_role = clerk_metadata.get("role", "")
    if clerk_role in ["admin", "org:admin", "owner"]:
        return

    permissions = ctx.get("permissions")
    if permissions:
        db_role = permissions.get("role", "")
        if db_role in ["admin", "owner"]:
            return

    raise HTTPException(
        status_code=403,
        detail="Admin access required"
    )


@router.get("/status")
async def get_diagnostics_status_envelope(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/admin/diagnostics/status

    Returns available diagnostic agents with JSON envelope.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        agents = [
            {
                "id": "health",
                "name": "Health Agent",
                "description": "System health analysis",
                "available": True,
            },
            {
                "id": "performance",
                "name": "Performance Agent",
                "description": "Response times & resource usage",
                "available": True,
            },
            {
                "id": "security",
                "name": "Security Agent",
                "description": "Auth & vulnerability checks",
                "available": True,
            },
            {
                "id": "bugs",
                "name": "Bug Detection Agent",
                "description": "Error tracking & exception analysis",
                "available": True,
            },
        ]

        return ok(
            data={
                "agents": agents,
                "mode": "manual_only",
                "note": "Diagnostics are advisory-only and read-only",
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail),
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        return error(
            message="Internal error fetching diagnostic status",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.post("/run/{agent_type}")
async def run_diagnostic_envelope(
    agent_type: Literal["health", "performance", "security", "bugs"],
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/admin/diagnostics/run/{agent_type}

    Run a diagnostic agent with JSON envelope response.
    Manual-run only, no polling.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        # Import the actual diagnostic functions from admin_actions_api
        from app.routers.admin_actions_api import (
            diagnose_health,
            diagnose_performance,
            diagnose_security,
            diagnose_bugs,
            DiagnosticRequest,
        )

        # Parse request body
        try:
            body = await request.json()
        except Exception:
            body = {}

        diagnostic_request = DiagnosticRequest(
            type=agent_type,
            depth=body.get("depth", "standard"),
            include_fixes=body.get("include_fixes", True),
        )

        # Run the appropriate diagnostic
        if agent_type == "health":
            result = await diagnose_health(diagnostic_request, ctx)
        elif agent_type == "performance":
            result = await diagnose_performance(diagnostic_request, ctx)
        elif agent_type == "security":
            result = await diagnose_security(diagnostic_request, ctx)
        elif agent_type == "bugs":
            result = await diagnose_bugs(diagnostic_request, ctx)
        else:
            return error(
                message=f"Unknown agent type: {agent_type}",
                request_id=request_id,
                status_code=400,
            )

        # Convert Pydantic model to dict if needed
        if hasattr(result, "model_dump"):
            result_data = result.model_dump()
        elif hasattr(result, "dict"):
            result_data = result.dict()
        else:
            result_data = result

        return ok(
            data=result_data,
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
            details=e.detail if isinstance(e.detail, dict) else None,
        )
    except Exception as e:
        # Log the full traceback for debugging
        tb = traceback.format_exc()
        print(f"[DIAGNOSTIC ERROR] request_id={request_id}\n{tb}")

        return error(
            message="Diagnostic execution failed",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.get("/last/{agent_type}")
async def get_last_diagnostic_envelope(
    agent_type: Literal["health", "performance", "security", "bugs"],
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/admin/diagnostics/last/{agent_type}

    Get last diagnostic result with JSON envelope.
    Read-only, advisory-only.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        # For now, return empty last run (in-memory storage doesn't persist across requests)
        # Production would use Redis/DB
        return ok(
            data={
                "agent": agent_type,
                "last_run": None,
                "message": "No previous run found. Run a diagnostic first.",
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail),
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        return error(
            message="Failed to fetch last diagnostic",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )

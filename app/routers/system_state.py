# app/routers/system_state.py
"""
System State API - Incident Mode + Rollback (Step 16)

Admin-only endpoints for managing system state:
- GET /system/state - Get current system state
- POST /system/incident/on - Enable incident mode
- POST /system/incident/off - Disable incident mode
- POST /system/rollback - Rollback to last approved deploy run
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import get_db_connection
from app.auth_context import get_current_identity, AuthIdentity


router = APIRouter(prefix="/system", tags=["system"])


# =============================================================================
# MODELS
# =============================================================================

class SystemStateResponse(BaseModel):
    id: int
    incident_mode: bool
    last_rollback_at: Optional[str]
    rolled_back_to_run_id: Optional[str]
    updated_at: str


class IncidentResponse(BaseModel):
    status: str
    incident_mode: bool


class RollbackResponse(BaseModel):
    status: str
    rolled_back_to_run_id: str
    rolled_back_at: str


# =============================================================================
# ADMIN DEPENDENCY
# =============================================================================

async def require_admin(identity: AuthIdentity = Depends(get_current_identity)) -> AuthIdentity:
    """Require admin role for system state operations."""
    user_id = identity["user_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT role FROM organization_members
        WHERE user_id = ? AND is_active = 1 AND role IN ('admin', 'owner')
        LIMIT 1
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for system operations"
        )

    return identity


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/state", response_model=SystemStateResponse)
async def get_state():
    """Get current system state. Public endpoint for status checking."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM system_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        # Initialize if not exists
        return SystemStateResponse(
            id=1,
            incident_mode=False,
            last_rollback_at=None,
            rolled_back_to_run_id=None,
            updated_at=datetime.utcnow().isoformat()
        )

    return SystemStateResponse(
        id=row["id"],
        incident_mode=bool(row["incident_mode"]),
        last_rollback_at=row.get("last_rollback_at"),
        rolled_back_to_run_id=row.get("rolled_back_to_run_id"),
        updated_at=row["updated_at"]
    )


@router.post("/incident/on", response_model=IncidentResponse)
async def incident_on(identity: AuthIdentity = Depends(require_admin)):
    """Enable incident mode. Blocks all non-admin requests. Admin-only."""
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.utcnow().isoformat()
    cursor.execute(
        "UPDATE system_state SET incident_mode = 1, updated_at = ? WHERE id = 1",
        (now,)
    )
    conn.commit()
    conn.close()

    return IncidentResponse(status="incident_on", incident_mode=True)


@router.post("/incident/off", response_model=IncidentResponse)
async def incident_off(identity: AuthIdentity = Depends(require_admin)):
    """Disable incident mode. Admin-only."""
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.utcnow().isoformat()
    cursor.execute(
        "UPDATE system_state SET incident_mode = 0, updated_at = ? WHERE id = 1",
        (now,)
    )
    conn.commit()
    conn.close()

    return IncidentResponse(status="incident_off", incident_mode=False)


@router.post("/rollback", response_model=RollbackResponse)
async def rollback(identity: AuthIdentity = Depends(require_admin)):
    """
    Rollback to the last approved deploy run.
    Sets the latest run status to 'rolled_back' and records the rollback.
    Admin-only.
    """
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Find the last approved run (excluding already rolled back)
    cursor.execute(
        """
        SELECT id, status FROM deploy_runs
        WHERE status = 'approved'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    approved_run = cursor.fetchone()

    if not approved_run:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No approved deploy run found to rollback to"
        )

    now = datetime.utcnow().isoformat()
    run_id = approved_run["id"]

    # Update the current run to rolled_back status
    cursor.execute(
        "UPDATE deploy_runs SET status = 'rolled_back' WHERE id = ?",
        (run_id,)
    )

    # Update system state with rollback info
    cursor.execute(
        """
        UPDATE system_state
        SET last_rollback_at = ?, rolled_back_to_run_id = ?, updated_at = ?
        WHERE id = 1
        """,
        (now, run_id, now)
    )

    conn.commit()
    conn.close()

    return RollbackResponse(
        status="rolled_back",
        rolled_back_to_run_id=run_id,
        rolled_back_at=now
    )


@router.get("/health")
async def system_health():
    """Quick system health check including incident mode status."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute("SELECT incident_mode FROM system_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    incident_mode = bool(row["incident_mode"]) if row else False

    return {
        "status": "degraded" if incident_mode else "healthy",
        "incident_mode": incident_mode
    }

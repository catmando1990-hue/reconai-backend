# app/routers/deploy_runs.py
"""
Deploy Runs API - Run Lifecycle + Approval Gate (Step 15)

Admin-only endpoints for managing deployment runs:
- POST /runs/initiate - Create a new deploy run (draft)
- GET /runs/latest - Get the latest deploy run
- POST /runs/{run_id}/approve - Approve a deploy run
- GET /runs/{run_id} - Get a specific deploy run
- POST /runs/{run_id}/status - Update run status
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import get_db_connection
from app.auth_context import get_current_identity, AuthIdentity
from app.middleware.rbac import rbac
from app.models_multitenancy import UserRole


router = APIRouter(prefix="/runs", tags=["runs"])


# =============================================================================
# MODELS
# =============================================================================

class InitiateRunRequest(BaseModel):
    commit_sha: str
    preview_url: Optional[str] = None


class ApproveRunRequest(BaseModel):
    signature: str


class UpdateStatusRequest(BaseModel):
    status: str  # 'draft', 'preview', 'approved', 'shipped', 'rolled_back'


class DeployRunResponse(BaseModel):
    id: str
    status: str
    commit_sha: str
    preview_url: Optional[str]
    initiated_by: str
    approved_by: Optional[str]
    approval_signature: Optional[str]
    created_at: str


# =============================================================================
# ADMIN DEPENDENCY
# =============================================================================

async def require_admin(identity: AuthIdentity = Depends(get_current_identity)) -> AuthIdentity:
    """
    Require admin role for deploy run operations.
    Checks if user has admin or owner role in any organization they belong to.
    """
    user_id = identity["user_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Check if user has admin or owner role in any org
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
            detail="Admin role required for deploy run operations"
        )

    return identity


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/initiate", response_model=DeployRunResponse)
async def initiate_run(
    payload: InitiateRunRequest,
    identity: AuthIdentity = Depends(require_admin)
):
    """
    Initiate a new deploy run. Creates a run in 'draft' status.
    Admin-only.
    """
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO deploy_runs (id, status, commit_sha, preview_url, initiated_by, created_at)
        VALUES (?, 'draft', ?, ?, ?, ?)
        """,
        (run_id, payload.commit_sha, payload.preview_url, identity["user_id"], now)
    )
    conn.commit()

    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    return DeployRunResponse(**row)


@router.get("/latest", response_model=Optional[DeployRunResponse])
async def get_latest_run():
    """
    Get the latest deploy run. Public endpoint for status checking.
    """
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM deploy_runs ORDER BY created_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return DeployRunResponse(**row)


@router.get("/{run_id}", response_model=DeployRunResponse)
async def get_run(run_id: str):
    """
    Get a specific deploy run by ID.
    """
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy run {run_id} not found"
        )

    return DeployRunResponse(**row)


@router.post("/{run_id}/approve", response_model=DeployRunResponse)
async def approve_run(
    run_id: str,
    payload: ApproveRunRequest,
    identity: AuthIdentity = Depends(require_admin)
):
    """
    Approve a deploy run. Sets status to 'approved' and records approver.
    Admin-only.
    """
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Check run exists
    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy run {run_id} not found"
        )

    # Update to approved
    cursor.execute(
        """
        UPDATE deploy_runs
        SET status = 'approved', approved_by = ?, approval_signature = ?
        WHERE id = ?
        """,
        (identity["user_id"], payload.signature, run_id)
    )
    conn.commit()

    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    updated_row = cursor.fetchone()
    conn.close()

    return DeployRunResponse(**updated_row)


@router.post("/{run_id}/status", response_model=DeployRunResponse)
async def update_run_status(
    run_id: str,
    payload: UpdateStatusRequest,
    identity: AuthIdentity = Depends(require_admin)
):
    """
    Update the status of a deploy run.
    Admin-only.
    """
    valid_statuses = ['draft', 'preview', 'approved', 'shipped', 'rolled_back']
    if payload.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Check run exists
    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy run {run_id} not found"
        )

    # Update status
    cursor.execute(
        "UPDATE deploy_runs SET status = ? WHERE id = ?",
        (payload.status, run_id)
    )
    conn.commit()

    cursor.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,))
    updated_row = cursor.fetchone()
    conn.close()

    return DeployRunResponse(**updated_row)


@router.get("/", response_model=list[DeployRunResponse])
async def list_runs(limit: int = 20):
    """
    List recent deploy runs.
    """
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM deploy_runs ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [DeployRunResponse(**row) for row in rows]

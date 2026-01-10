# app/routers/governance.py
"""
Governance API - Steps 17-19

- Step 17: Multi-Approver Release Gate
- Step 18: Immutable Audit Log
- Step 19: Feature Flags tied to Run State
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import get_db_connection
from app.auth_context import get_current_identity, AuthIdentity


router = APIRouter(prefix="/governance", tags=["governance"])


# =============================================================================
# MODELS
# =============================================================================

class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    approved_by: str
    approved_at: str


class AuditLogEntry(BaseModel):
    id: str
    action: str
    actor: str
    run_id: Optional[str]
    metadata: Optional[dict]
    created_at: str


class FeatureFlag(BaseModel):
    id: str
    name: str
    enabled: bool
    run_id: Optional[str]
    description: Optional[str]
    created_at: str
    updated_at: str


class CreateFeatureFlagRequest(BaseModel):
    name: str
    enabled: bool = False
    description: Optional[str] = None
    run_id: Optional[str] = None


class UpdateFeatureFlagRequest(BaseModel):
    enabled: Optional[bool] = None
    description: Optional[str] = None
    run_id: Optional[str] = None


# =============================================================================
# ADMIN DEPENDENCY
# =============================================================================

async def require_admin(identity: AuthIdentity = Depends(get_current_identity)) -> AuthIdentity:
    """Require admin role for governance operations."""
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
            detail="Admin role required for governance operations"
        )

    return identity


# =============================================================================
# AUDIT LOG HELPER
# =============================================================================

def log_audit(action: str, actor: str, run_id: Optional[str] = None, metadata: Optional[dict] = None):
    """Log an action to the immutable audit log."""
    conn = get_db_connection()
    cursor = conn.cursor()

    audit_id = str(uuid.uuid4())
    metadata_json = json.dumps(metadata) if metadata else None

    cursor.execute(
        """
        INSERT INTO audit_log (id, action, actor, run_id, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (audit_id, action, actor, run_id, metadata_json)
    )
    conn.commit()
    conn.close()


# =============================================================================
# STEP 17: MULTI-APPROVER RELEASE GATE
# =============================================================================

@router.post("/approve/{run_id}", response_model=ApprovalResponse)
async def approve_run(
    run_id: str,
    identity: AuthIdentity = Depends(require_admin)
):
    """
    Add an approval to a deploy run.
    Multiple admins can approve the same run.
    """
    user_id = identity["user_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Check run exists
    cursor.execute("SELECT id, status FROM deploy_runs WHERE id = ?", (run_id,))
    run = cursor.fetchone()

    if not run:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy run {run_id} not found"
        )

    # Check if user already approved
    cursor.execute(
        "SELECT id FROM deploy_run_approvals WHERE run_id = ? AND approved_by = ?",
        (run_id, user_id)
    )
    existing = cursor.fetchone()

    if existing:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already approved this run"
        )

    # Add approval
    approval_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    cursor.execute(
        "INSERT INTO deploy_run_approvals (id, run_id, approved_by, approved_at) VALUES (?, ?, ?, ?)",
        (approval_id, run_id, user_id, now)
    )

    # Update run status to approved
    cursor.execute(
        "UPDATE deploy_runs SET status = 'approved', approved_by = ? WHERE id = ?",
        (user_id, run_id)
    )

    conn.commit()
    conn.close()

    # Log to audit
    log_audit("run_approved", user_id, run_id, {"approval_id": approval_id})

    return ApprovalResponse(
        id=approval_id,
        run_id=run_id,
        approved_by=user_id,
        approved_at=now
    )


@router.get("/approvals/{run_id}", response_model=List[ApprovalResponse])
async def get_run_approvals(run_id: str):
    """Get all approvals for a deploy run."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM deploy_run_approvals WHERE run_id = ? ORDER BY approved_at",
        (run_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [ApprovalResponse(**row) for row in rows]


# =============================================================================
# STEP 18: IMMUTABLE AUDIT LOG
# =============================================================================

@router.get("/audit", response_model=List[AuditLogEntry])
async def get_audit_log(
    limit: int = 100,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    identity: AuthIdentity = Depends(require_admin)
):
    """Get audit log entries. Admin-only."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if action:
        query += " AND action = ?"
        params.append(action)

    if actor:
        query += " AND actor = ?"
        params.append(actor)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        metadata = None
        if row.get("metadata"):
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                metadata = {"raw": row["metadata"]}

        result.append(AuditLogEntry(
            id=row["id"],
            action=row["action"],
            actor=row["actor"],
            run_id=row.get("run_id"),
            metadata=metadata,
            created_at=row["created_at"]
        ))

    return result


# =============================================================================
# STEP 19: FEATURE FLAGS TIED TO RUN STATE
# =============================================================================

@router.get("/features", response_model=List[FeatureFlag])
async def get_features(enabled_only: bool = False):
    """Get all feature flags. Public endpoint."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    if enabled_only:
        cursor.execute("SELECT * FROM feature_flags WHERE enabled = 1 ORDER BY name")
    else:
        cursor.execute("SELECT * FROM feature_flags ORDER BY name")

    rows = cursor.fetchall()
    conn.close()

    return [FeatureFlag(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        run_id=row.get("run_id"),
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    ) for row in rows]


@router.get("/features/{name}")
async def get_feature(name: str):
    """Get a specific feature flag by name. Public endpoint."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM feature_flags WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"name": name, "enabled": False}

    return FeatureFlag(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        run_id=row.get("run_id"),
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )


@router.post("/features", response_model=FeatureFlag)
async def create_feature(
    payload: CreateFeatureFlagRequest,
    identity: AuthIdentity = Depends(require_admin)
):
    """Create a new feature flag. Admin-only."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    # Check if exists
    cursor.execute("SELECT id FROM feature_flags WHERE name = ?", (payload.name,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feature flag '{payload.name}' already exists"
        )

    flag_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO feature_flags (id, name, enabled, run_id, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (flag_id, payload.name, 1 if payload.enabled else 0, payload.run_id, payload.description, now, now)
    )
    conn.commit()

    cursor.execute("SELECT * FROM feature_flags WHERE id = ?", (flag_id,))
    row = cursor.fetchone()
    conn.close()

    # Log to audit
    log_audit("feature_flag_created", identity["user_id"], payload.run_id, {
        "flag_id": flag_id,
        "name": payload.name,
        "enabled": payload.enabled
    })

    return FeatureFlag(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        run_id=row.get("run_id"),
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )


@router.patch("/features/{name}", response_model=FeatureFlag)
async def update_feature(
    name: str,
    payload: UpdateFeatureFlagRequest,
    identity: AuthIdentity = Depends(require_admin)
):
    """Update a feature flag. Admin-only."""
    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM feature_flags WHERE name = ?", (name,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{name}' not found"
        )

    updates = []
    params = []

    if payload.enabled is not None:
        updates.append("enabled = ?")
        params.append(1 if payload.enabled else 0)

    if payload.description is not None:
        updates.append("description = ?")
        params.append(payload.description)

    if payload.run_id is not None:
        updates.append("run_id = ?")
        params.append(payload.run_id)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(name)

        cursor.execute(
            f"UPDATE feature_flags SET {', '.join(updates)} WHERE name = ?",
            params
        )
        conn.commit()

    cursor.execute("SELECT * FROM feature_flags WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()

    # Log to audit
    log_audit("feature_flag_updated", identity["user_id"], row.get("run_id"), {
        "name": name,
        "changes": payload.model_dump(exclude_none=True)
    })

    return FeatureFlag(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        run_id=row.get("run_id"),
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )


@router.delete("/features/{name}")
async def delete_feature(
    name: str,
    identity: AuthIdentity = Depends(require_admin)
):
    """Delete a feature flag. Admin-only."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM feature_flags WHERE name = ?", (name,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{name}' not found"
        )

    # Log to audit
    log_audit("feature_flag_deleted", identity["user_id"], None, {"name": name})

    return {"deleted": True, "name": name}

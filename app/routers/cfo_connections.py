# app/routers/cfo_connections.py
"""
CFO Tier Bank Connections API

Supports both Plaid Link and manual account entry.
Data is isolated to cfo_connections table.

CANONICAL LAWS:
- All queries filter by organization_id (org isolation)
- Audit logging for all mutations
- Soft delete (status = 'inactive') instead of hard delete
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any, List
from uuid import uuid4

from app.auth_context import get_current_context, AuthContext
from app.db import get_db_connection
from app.services.audit_service import record_audit


router = APIRouter(prefix="/api/cfo", tags=["CFO Connections"])


# =============================================================================
# MODELS
# =============================================================================

class PlaidConnectionRequest(BaseModel):
    """Request to create a CFO connection via Plaid."""
    public_token: str
    institution_id: str
    institution_name: str


class ManualConnectionRequest(BaseModel):
    """Request to create a CFO connection via manual entry."""
    institution_name: str = Field(..., min_length=1, max_length=100)
    account_name: str = Field(..., min_length=1, max_length=100)
    account_type: Literal["checking", "savings", "credit", "investment", "other"]
    account_mask: Optional[str] = Field(None, max_length=4)


class ConnectionResponse(BaseModel):
    """Response model for a CFO connection."""
    id: str
    connection_type: str
    institution_name: Optional[str]
    account_name: Optional[str]
    account_type: Optional[str]
    status: str
    last_synced_at: Optional[str]
    created_at: str


# =============================================================================
# HELPERS
# =============================================================================

def _generate_request_id() -> str:
    """Generate unique request ID for audit trail."""
    return f"req_{uuid4().hex[:12]}"


def _generate_connection_id() -> str:
    """Generate unique connection ID."""
    return f"cfo_conn_{uuid4().hex[:12]}"


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/connections")
async def list_cfo_connections(
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """List all CFO tier bank connections for the organization."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        cursor = conn.execute("""
            SELECT id, connection_type,
                   COALESCE(plaid_institution_name, institution_name) as institution_name,
                   account_name, account_type, account_mask,
                   status, last_synced_at, error_message, created_at
            FROM cfo_connections
            WHERE organization_id = ? AND status != 'inactive'
            ORDER BY created_at DESC
        """, (org_id,))

        rows = cursor.fetchall()

        return {
            "status": "ok",
            "connections": rows,
            "total": len(rows),
            "request_id": request_id
        }
    finally:
        conn.close()


@router.post("/connections/plaid", status_code=status.HTTP_201_CREATED)
async def create_plaid_connection(
    request: PlaidConnectionRequest,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Create a CFO connection via Plaid Link.

    Note: This endpoint expects the public_token from Plaid Link.
    The token exchange should be handled by a Plaid service.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    connection_id = _generate_connection_id()

    # Note: In production, you would exchange the public_token for an access_token
    # using your Plaid service. For now, we store the metadata.
    # access_token, item_id = await exchange_public_token(request.public_token)

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO cfo_connections (
                id, organization_id, connection_type,
                plaid_institution_id, plaid_institution_name,
                status, created_by
            ) VALUES (?, ?, 'plaid', ?, ?, 'active', ?)
        """, (
            connection_id,
            org_id,
            request.institution_id,
            request.institution_name,
            user_id,
        ))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="cfo_connection_created",
            entity="cfo_connection",
            entity_id=connection_id,
            payload={
                "type": "plaid",
                "institution": request.institution_name,
                "institution_id": request.institution_id,
            },
            request_id=request_id,
        )

        return {
            "status": "ok",
            "id": connection_id,
            "connection_status": "active",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.post("/connections/manual", status_code=status.HTTP_201_CREATED)
async def create_manual_connection(
    request: ManualConnectionRequest,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Create a CFO connection via manual entry."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    connection_id = _generate_connection_id()

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO cfo_connections (
                id, organization_id, connection_type,
                institution_name, account_name, account_type, account_mask,
                status, created_by
            ) VALUES (?, ?, 'manual', ?, ?, ?, ?, 'active', ?)
        """, (
            connection_id,
            org_id,
            request.institution_name,
            request.account_name,
            request.account_type,
            request.account_mask,
            user_id,
        ))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="cfo_connection_created",
            entity="cfo_connection",
            entity_id=connection_id,
            payload={
                "type": "manual",
                "institution": request.institution_name,
                "account_type": request.account_type,
            },
            request_id=request_id,
        )

        return {
            "status": "ok",
            "id": connection_id,
            "connection_status": "active",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.get("/connections/{connection_id}")
async def get_cfo_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Get a single CFO connection by ID."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        cursor = conn.execute("""
            SELECT id, connection_type,
                   COALESCE(plaid_institution_name, institution_name) as institution_name,
                   account_name, account_type, account_mask,
                   status, last_synced_at, error_message, created_at, updated_at
            FROM cfo_connections
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Connection not found", "request_id": request_id}
            )

        return {
            "status": "ok",
            "data": row,
            "request_id": request_id
        }
    finally:
        conn.close()


@router.delete("/connections/{connection_id}")
async def delete_cfo_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Remove a CFO bank connection (soft delete).

    Sets status to 'inactive' rather than deleting the record.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership
        cursor = conn.execute("""
            SELECT id, status FROM cfo_connections
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Connection not found", "request_id": request_id}
            )

        if row[1] == "inactive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "ALREADY_INACTIVE", "message": "Connection already removed", "request_id": request_id}
            )

        conn.execute("""
            UPDATE cfo_connections
            SET status = 'inactive', updated_at = datetime('now')
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="cfo_connection_removed",
            entity="cfo_connection",
            entity_id=connection_id,
            payload={},
            request_id=request_id,
        )

        return {
            "status": "ok",
            "message": "Connection removed",
            "request_id": request_id
        }
    finally:
        conn.close()

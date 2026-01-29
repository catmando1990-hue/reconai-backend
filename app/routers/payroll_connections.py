# app/routers/payroll_connections.py
"""
Payroll Tier Bank Connections API

Supports both Plaid Link and manual account entry.
Includes payroll-specific fields like account purpose.

CANONICAL LAWS:
- All queries filter by organization_id (org isolation)
- Audit logging for all mutations
- Soft delete (status = 'inactive') instead of hard delete
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any
from uuid import uuid4

from app.auth_context import get_current_context, AuthContext
from app.db import get_db_connection
from app.services.audit_service import record_audit


router = APIRouter(prefix="/api/payroll", tags=["Payroll Connections"])


# =============================================================================
# MODELS
# =============================================================================

class PlaidConnectionRequest(BaseModel):
    """Request to create a Payroll connection via Plaid."""
    public_token: str
    institution_id: str
    institution_name: str
    purpose: Literal["payroll_funding", "tax_payments", "benefits", "general"] = "general"


class ManualConnectionRequest(BaseModel):
    """Request to create a Payroll connection via manual entry."""
    institution_name: str = Field(..., min_length=1, max_length=100)
    account_name: str = Field(..., min_length=1, max_length=100)
    account_type: Literal["checking", "savings", "payroll"]
    account_mask: Optional[str] = Field(None, max_length=4)
    purpose: Literal["payroll_funding", "tax_payments", "benefits", "general"]


class ConnectionUpdateRequest(BaseModel):
    """Request to update a Payroll connection."""
    purpose: Optional[Literal["payroll_funding", "tax_payments", "benefits", "general"]] = None
    account_name: Optional[str] = None


# =============================================================================
# HELPERS
# =============================================================================

def _generate_request_id() -> str:
    """Generate unique request ID for audit trail."""
    return f"req_{uuid4().hex[:12]}"


def _generate_connection_id() -> str:
    """Generate unique connection ID."""
    return f"pay_conn_{uuid4().hex[:12]}"


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/connections")
async def list_payroll_connections(
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """List all Payroll tier bank connections for the organization."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        cursor = conn.execute("""
            SELECT id, connection_type,
                   COALESCE(plaid_institution_name, institution_name) as institution_name,
                   account_name, account_type, account_mask, purpose,
                   status, last_synced_at, error_message, created_at
            FROM payroll_connections
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
    Create a Payroll connection via Plaid Link.

    Note: This endpoint expects the public_token from Plaid Link.
    The token exchange should be handled by a Plaid service.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    connection_id = _generate_connection_id()

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO payroll_connections (
                id, organization_id, connection_type,
                plaid_institution_id, plaid_institution_name,
                purpose, status, created_by
            ) VALUES (?, ?, 'plaid', ?, ?, ?, 'active', ?)
        """, (
            connection_id,
            org_id,
            request.institution_id,
            request.institution_name,
            request.purpose,
            user_id,
        ))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="payroll_connection_created",
            entity="payroll_connection",
            entity_id=connection_id,
            payload={
                "type": "plaid",
                "institution": request.institution_name,
                "purpose": request.purpose,
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
    """Create a Payroll connection via manual entry."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    connection_id = _generate_connection_id()

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO payroll_connections (
                id, organization_id, connection_type,
                institution_name, account_name, account_type, account_mask,
                purpose, status, created_by
            ) VALUES (?, ?, 'manual', ?, ?, ?, ?, ?, 'active', ?)
        """, (
            connection_id,
            org_id,
            request.institution_name,
            request.account_name,
            request.account_type,
            request.account_mask,
            request.purpose,
            user_id,
        ))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="payroll_connection_created",
            entity="payroll_connection",
            entity_id=connection_id,
            payload={
                "type": "manual",
                "institution": request.institution_name,
                "account_type": request.account_type,
                "purpose": request.purpose,
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
async def get_payroll_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Get a single Payroll connection by ID."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        cursor = conn.execute("""
            SELECT id, connection_type,
                   COALESCE(plaid_institution_name, institution_name) as institution_name,
                   account_name, account_type, account_mask, purpose,
                   status, last_synced_at, error_message, created_at, updated_at
            FROM payroll_connections
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


@router.patch("/connections/{connection_id}")
async def update_payroll_connection(
    connection_id: str,
    request: ConnectionUpdateRequest,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Update a Payroll connection (e.g., change purpose)."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership
        cursor = conn.execute("""
            SELECT id, status FROM payroll_connections
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Connection not found", "request_id": request_id}
            )

        # Build update query
        updates = []
        params = []
        if request.purpose is not None:
            updates.append("purpose = ?")
            params.append(request.purpose)
        if request.account_name is not None:
            updates.append("account_name = ?")
            params.append(request.account_name)

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "NO_UPDATES", "message": "No fields to update", "request_id": request_id}
            )

        updates.append("updated_at = datetime('now')")
        params.extend([connection_id, org_id])

        conn.execute(f"""
            UPDATE payroll_connections
            SET {', '.join(updates)}
            WHERE id = ? AND organization_id = ?
        """, params)
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="payroll_connection_updated",
            entity="payroll_connection",
            entity_id=connection_id,
            payload=request.model_dump(exclude_none=True),
            request_id=request_id,
        )

        return {
            "status": "ok",
            "message": "Connection updated",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.delete("/connections/{connection_id}")
async def delete_payroll_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Remove a Payroll bank connection (soft delete).

    Sets status to 'inactive' rather than deleting the record.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership
        cursor = conn.execute("""
            SELECT id, status FROM payroll_connections
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
            UPDATE payroll_connections
            SET status = 'inactive', updated_at = datetime('now')
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="payroll_connection_removed",
            entity="payroll_connection",
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

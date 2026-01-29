# app/routers/govcon_connections.py
"""
GovCon Tier Bank Connections API

MANUAL ONLY for DCAA compliance.
Requires authorization documentation and verification.

CANONICAL LAWS:
- All queries filter by organization_id (org isolation)
- Manual entry only (no Plaid) for DCAA audit trail
- Connections start in 'pending_verification' status
- Verification requires separate endpoint call
- Audit logging for all mutations
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any
from uuid import uuid4

from app.auth_context import get_current_context, AuthContext
from app.db import get_db_connection
from app.services.audit_service import record_audit


router = APIRouter(prefix="/api/govcon", tags=["GovCon Connections"])


# =============================================================================
# MODELS
# =============================================================================

class GovConConnectionRequest(BaseModel):
    """Request to create a GovCon connection (manual only)."""
    institution_name: str = Field(..., min_length=1, max_length=100)
    account_name: str = Field(..., min_length=1, max_length=100)
    account_type: Literal["checking", "savings", "trust", "escrow"]
    account_number_last4: Optional[str] = Field(None, max_length=4)
    routing_number_last4: Optional[str] = Field(None, max_length=4)
    contract_id: Optional[str] = None
    cost_pool: Literal["direct", "indirect", "overhead", "g_and_a", "fringe"]
    authorization_date: str = Field(..., description="YYYY-MM-DD format")
    authorized_by: str = Field(..., min_length=1, max_length=100)
    evidence_document_id: Optional[str] = None


class ConnectionUpdateRequest(BaseModel):
    """Request to update a GovCon connection."""
    contract_id: Optional[str] = None
    cost_pool: Optional[Literal["direct", "indirect", "overhead", "g_and_a", "fringe"]] = None
    evidence_document_id: Optional[str] = None


# =============================================================================
# HELPERS
# =============================================================================

def _generate_request_id() -> str:
    """Generate unique request ID for audit trail."""
    return f"req_{uuid4().hex[:12]}"


def _generate_connection_id() -> str:
    """Generate unique connection ID."""
    return f"gc_conn_{uuid4().hex[:12]}"


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/connections")
async def list_govcon_connections(
    ctx: AuthContext = Depends(get_current_context),
    contract_id: Optional[str] = None,
    cost_pool: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all GovCon tier bank connections for the organization.

    Optional filters:
    - contract_id: Filter by linked contract
    - cost_pool: Filter by cost pool type
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        query = """
            SELECT id, connection_type, institution_name, account_name,
                   account_type, account_number_masked, routing_number_masked,
                   contract_id, cost_pool,
                   authorization_date, authorized_by, evidence_document_id,
                   status, verified_at, verified_by, created_at
            FROM govcon_connections
            WHERE organization_id = ? AND status != 'inactive'
        """
        params = [org_id]

        if contract_id:
            query += " AND contract_id = ?"
            params.append(contract_id)
        if cost_pool:
            query += " AND cost_pool = ?"
            params.append(cost_pool)

        query += " ORDER BY created_at DESC"

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return {
            "status": "ok",
            "connections": rows,
            "total": len(rows),
            "request_id": request_id
        }
    finally:
        conn.close()


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_govcon_connection(
    request: GovConConnectionRequest,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Create a GovCon bank connection (manual only).

    DCAA Compliance Notes:
    - All bank accounts must be manually verified
    - Authorization documentation is required
    - Connections start in 'pending_verification' status
    - Verification must be done via separate endpoint
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    connection_id = _generate_connection_id()

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO govcon_connections (
                id, organization_id, connection_type,
                institution_name, account_name, account_type,
                account_number_masked, routing_number_masked,
                contract_id, cost_pool,
                authorization_date, authorized_by, evidence_document_id,
                status, created_by
            ) VALUES (?, ?, 'manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_verification', ?)
        """, (
            connection_id,
            org_id,
            request.institution_name,
            request.account_name,
            request.account_type,
            request.account_number_last4,
            request.routing_number_last4,
            request.contract_id,
            request.cost_pool,
            request.authorization_date,
            request.authorized_by,
            request.evidence_document_id,
            user_id,
        ))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="govcon_connection_created",
            entity="govcon_connection",
            entity_id=connection_id,
            payload={
                "institution": request.institution_name,
                "account_type": request.account_type,
                "cost_pool": request.cost_pool,
                "authorized_by": request.authorized_by,
                "authorization_date": request.authorization_date,
                "contract_id": request.contract_id,
            },
            request_id=request_id,
        )

        return {
            "status": "ok",
            "id": connection_id,
            "connection_status": "pending_verification",
            "message": "Connection created. Awaiting verification.",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.get("/connections/{connection_id}")
async def get_govcon_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Get a single GovCon connection by ID."""
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    try:
        cursor = conn.execute("""
            SELECT id, connection_type, institution_name, account_name,
                   account_type, account_number_masked, routing_number_masked,
                   contract_id, cost_pool,
                   authorization_date, authorized_by, evidence_document_id,
                   status, verified_at, verified_by, created_at, updated_at
            FROM govcon_connections
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
async def update_govcon_connection(
    connection_id: str,
    request: ConnectionUpdateRequest,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Update a GovCon connection.

    Note: Cannot update core fields (institution, account) after creation.
    Only contract_id, cost_pool, and evidence_document_id can be updated.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership
        cursor = conn.execute("""
            SELECT id, status FROM govcon_connections
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
        if request.contract_id is not None:
            updates.append("contract_id = ?")
            params.append(request.contract_id)
        if request.cost_pool is not None:
            updates.append("cost_pool = ?")
            params.append(request.cost_pool)
        if request.evidence_document_id is not None:
            updates.append("evidence_document_id = ?")
            params.append(request.evidence_document_id)

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "NO_UPDATES", "message": "No fields to update", "request_id": request_id}
            )

        updates.append("updated_at = datetime('now')")
        params.extend([connection_id, org_id])

        conn.execute(f"""
            UPDATE govcon_connections
            SET {', '.join(updates)}
            WHERE id = ? AND organization_id = ?
        """, params)
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="govcon_connection_updated",
            entity="govcon_connection",
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


@router.post("/connections/{connection_id}/verify")
async def verify_govcon_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Verify a GovCon bank connection.

    DCAA Compliance Notes:
    - This should only be done after reviewing authorization documentation
    - Verification is a one-way operation (cannot un-verify)
    - The verifier (current user) is recorded for audit trail
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership and status
        cursor = conn.execute("""
            SELECT status, evidence_document_id FROM govcon_connections
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Connection not found", "request_id": request_id}
            )

        current_status = row[0]

        if current_status == "verified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "ALREADY_VERIFIED", "message": "Connection already verified", "request_id": request_id}
            )

        if current_status == "inactive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INACTIVE", "message": "Cannot verify inactive connection", "request_id": request_id}
            )

        conn.execute("""
            UPDATE govcon_connections
            SET status = 'verified',
                verified_at = datetime('now'),
                verified_by = ?,
                updated_at = datetime('now')
            WHERE id = ? AND organization_id = ?
        """, (user_id, connection_id, org_id))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="govcon_connection_verified",
            entity="govcon_connection",
            entity_id=connection_id,
            payload={
                "verified_by": user_id,
            },
            request_id=request_id,
        )

        return {
            "status": "ok",
            "connection_status": "verified",
            "message": "Connection verified successfully",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.post("/connections/{connection_id}/reject")
async def reject_govcon_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Reject a GovCon bank connection that failed verification.

    Use this when authorization documentation is insufficient or invalid.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership and status
        cursor = conn.execute("""
            SELECT status FROM govcon_connections
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Connection not found", "request_id": request_id}
            )

        current_status = row[0]

        if current_status == "verified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "ALREADY_VERIFIED", "message": "Cannot reject verified connection", "request_id": request_id}
            )

        conn.execute("""
            UPDATE govcon_connections
            SET status = 'rejected',
                updated_at = datetime('now')
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="govcon_connection_rejected",
            entity="govcon_connection",
            entity_id=connection_id,
            payload={
                "rejected_by": user_id,
            },
            request_id=request_id,
        )

        return {
            "status": "ok",
            "connection_status": "rejected",
            "message": "Connection rejected",
            "request_id": request_id
        }
    finally:
        conn.close()


@router.delete("/connections/{connection_id}")
async def delete_govcon_connection(
    connection_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Remove a GovCon bank connection (soft delete).

    Sets status to 'inactive' rather than deleting the record.
    DCAA requires maintaining the audit trail.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    conn = get_db_connection()
    try:
        # Verify ownership
        cursor = conn.execute("""
            SELECT id, status FROM govcon_connections
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
            UPDATE govcon_connections
            SET status = 'inactive', updated_at = datetime('now')
            WHERE id = ? AND organization_id = ?
        """, (connection_id, org_id))
        conn.commit()

        # Audit
        record_audit(
            actor=user_id,
            action="govcon_connection_removed",
            entity="govcon_connection",
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

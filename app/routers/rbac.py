# app/routers/rbac.py
# Phase 73 — Enterprise RBAC Expansion
# Phase 5.2 — GET /api/rbac (P1 Endpoint)

import sqlite3
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import List, Tuple

from app.models.rbac import RbacSnapshot, Permission
from app.auth_context import get_current_organization_id
from app.db import get_db_connection

router = APIRouter(prefix='/api/rbac', tags=['rbac'])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


# =============================================================================
# PHASE 5.2: P1 ENDPOINT — GET /api/rbac
# =============================================================================
# READ-ONLY snapshot of effective permissions from rbac_effective_permissions table
# - No aggregation logic beyond SELECT
# - No inference, no defaults
# - Org-isolated via organization_id filter

@router.get('/', tags=['rbac', 'p1'])
async def get_rbac_effective_permissions(
    request: Request,
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get effective permissions snapshot for the organization.

    Phase 5.2 P1 Endpoint — READ-ONLY

    Returns:
        items: List of role/permission pairs
        request_id: UUID for request tracing
    """
    request_id = _get_request_id(request)

    sql = """
        SELECT
            role,
            permission
        FROM rbac_effective_permissions
        WHERE organization_id = ?
        ORDER BY role ASC, permission ASC
    """

    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, (organization_id,))
        rows = cursor.fetchall()
        conn.close()

        items = [dict(row) for row in rows]
        return {"items": items, "request_id": request_id}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "rbac_query_failed",
                "detail": str(e),
                "request_id": request_id
            }
        )


# =============================================================================
# LEGACY ENDPOINT — /api/rbac/snapshot (backwards compatibility)
# =============================================================================
# Note: Path changed from /rbac/snapshot to /api/rbac/snapshot

# Replace with real auth extraction from Clerk/JWT
async def get_roles_permissions() -> Tuple[List[str], List[Permission]]:
    """Get user roles and permissions from auth context."""
    return ['user'], ['status.read']


@router.get('/snapshot', response_model=RbacSnapshot)
async def get_rbac_snapshot(
    rp: Tuple[List[str], List[Permission]] = Depends(get_roles_permissions)
):
    """
    Get current RBAC snapshot including roles and permissions.

    Designed to be fed from your existing auth provider claims.
    """
    roles, permissions = rp
    return RbacSnapshot(
        roles=roles,
        permissions=permissions,
        updatedAtISO=datetime.now(timezone.utc).isoformat(),
    )

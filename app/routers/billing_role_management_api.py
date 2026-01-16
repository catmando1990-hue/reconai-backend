# app/routers/billing_role_management_api.py
"""
ReconAI Billing — Role Management API

POST /api/billing/roles - Update billing roles for organization members
GET /api/billing/roles - List billing roles for organization

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: manage_roles permission required (owner, billing_admin)
- Manual invocation only (no auto-sync)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import sqlite3
from uuid import uuid4
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission, BILLING_PERMISSION_MATRIX

router = APIRouter(tags=["billing"])


class RoleUpdateRequest(BaseModel):
    user_id: str
    role: str  # owner | billing_admin | read_only


class BulkRoleUpdateRequest(BaseModel):
    updates: List[RoleUpdateRequest]


# Add manage_roles permission to RBAC matrix if not present
if "manage_roles" not in BILLING_PERMISSION_MATRIX:
    BILLING_PERMISSION_MATRIX["manage_roles"] = {"owner", "billing_admin"}


def _get_org_billing_roles(org_id: str) -> List[dict]:
    """Get billing roles for all members in an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        # Get owner
        cursor = conn.execute("""
            SELECT u.id, u.email, u.first_name, u.last_name, 'owner' as role
            FROM organizations o
            JOIN users u ON o.owner_user_id = u.id
            WHERE o.id = ?
        """, (org_id,))
        owner = cursor.fetchone()

        results = []
        if owner:
            results.append({
                "user_id": owner[0],
                "email": owner[1],
                "name": f"{owner[2] or ''} {owner[3] or ''}".strip() or owner[1],
                "role": "owner",
                "is_owner": True,
            })

        # Get members
        cursor = conn.execute("""
            SELECT u.id, u.email, u.first_name, u.last_name, om.role
            FROM organization_members om
            JOIN users u ON om.user_id = u.id
            WHERE om.organization_id = ? AND om.is_active = 1
        """, (org_id,))

        for row in cursor.fetchall():
            # Map org roles to billing roles
            org_role = row[4]
            billing_role = {
                "admin": "billing_admin",
                "billing_admin": "billing_admin",
                "member": "read_only",
                "viewer": "read_only",
            }.get(org_role, "read_only")

            results.append({
                "user_id": row[0],
                "email": row[1],
                "name": f"{row[2] or ''} {row[3] or ''}".strip() or row[1],
                "role": billing_role,
                "is_owner": False,
            })

        return results


def _update_member_billing_role(org_id: str, user_id: str, new_role: str) -> bool:
    """Update a member's billing role. Cannot change owner role."""
    # Map billing role to org role
    role_map = {
        "billing_admin": "admin",
        "read_only": "viewer",
    }
    org_role = role_map.get(new_role)

    if not org_role:
        return False

    with sqlite3.connect(DB_PATH) as conn:
        # Check not trying to modify owner
        cursor = conn.execute(
            "SELECT owner_user_id FROM organizations WHERE id = ?",
            (org_id,)
        )
        owner_row = cursor.fetchone()
        if owner_row and owner_row[0] == user_id:
            return False  # Cannot change owner's role

        # Update member role
        cursor = conn.execute("""
            UPDATE organization_members
            SET role = ?, updated_at = datetime('now')
            WHERE organization_id = ? AND user_id = ?
        """, (org_role, org_id, user_id))
        conn.commit()

        return cursor.rowcount > 0


@router.get("/api/billing/roles")
async def list_billing_roles(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    List billing roles for all members in the organization.

    RBAC: view_status permission (all authenticated users can view).
    Returns user_id, email, name, role, is_owner for each member.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check: view_status is sufficient to list roles
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    roles = _get_org_billing_roles(org_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "roles": roles,
    }


@router.post("/api/billing/roles")
async def update_billing_roles(
    payload: BulkRoleUpdateRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Update billing roles for organization members.

    RBAC: manage_roles permission required (owner, billing_admin).
    Cannot change the owner's role.
    Manual invocation only - no auto-sync.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check: manage_roles requires owner or billing_admin
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # Validate roles
    valid_roles = {"billing_admin", "read_only"}
    for update in payload.updates:
        if update.role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "INVALID_ROLE",
                    "message": f"Invalid role '{update.role}'. Must be one of: {', '.join(valid_roles)}",
                    "request_id": request_id,
                }
            )

    # Process updates
    results = []
    for update in payload.updates:
        success = _update_member_billing_role(org_id, update.user_id, update.role)
        results.append({
            "user_id": update.user_id,
            "role": update.role,
            "success": success,
            "error": "Cannot modify owner role" if not success else None,
        })

    # Audit log
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "BILLING_ROLES_UPDATED",
                user_id,
                str({"updates": [r for r in results if r["success"]]}),
            ))
            conn.commit()
    except Exception:
        pass  # Audit logging should not fail the request

    return {
        "request_id": request_id,
        "org_id": org_id,
        "status": "roles_updated",
        "results": results,
    }

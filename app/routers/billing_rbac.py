# app/routers/billing_rbac.py
"""
ReconAI Billing — Enterprise RBAC (Server-Side Permission Enforcement)

Roles:
- owner: Full billing access
- billing_admin: Full billing access
- read_only: View status and invoices only

Permissions (server-side enforced):
- view_status: owner, billing_admin, read_only
- view_invoices: owner, billing_admin, read_only
- sync_billing: owner, billing_admin
- upgrade: owner, billing_admin
- downgrade: owner, billing_admin
- cancel: owner, billing_admin
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional
from fastapi import HTTPException, status

from app.db import DB_PATH


@dataclass(frozen=True)
class BillingActor:
    """Represents a user's billing role within an organization."""
    user_id: str
    org_id: str
    role: str  # owner | billing_admin | read_only


# Permission matrix: permission -> set of allowed roles
BILLING_PERMISSION_MATRIX = {
    "view_status": {"owner", "billing_admin", "read_only"},
    "view_invoices": {"owner", "billing_admin", "read_only"},
    "sync_billing": {"owner", "billing_admin"},
    "upgrade": {"owner", "billing_admin"},
    "downgrade": {"owner", "billing_admin"},
    "cancel": {"owner", "billing_admin"},
    "manage_roles": {"owner", "billing_admin"},
}


def get_billing_actor(user_id: str, org_id: str) -> BillingActor:
    """
    Resolve a user's billing role for an organization.

    Checks:
    1. If user is organization owner -> "owner"
    2. If user has org member role -> map to billing role
    3. Default -> "read_only"
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Check if user is organization owner
        cursor = conn.execute(
            "SELECT owner_user_id FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()
        if row and row[0] == user_id:
            return BillingActor(user_id=user_id, org_id=org_id, role="owner")

        # Check organization membership role
        cursor = conn.execute("""
            SELECT role FROM organization_members
            WHERE organization_id = ? AND user_id = ? AND is_active = 1
        """, (org_id, user_id))
        row = cursor.fetchone()

        if row:
            org_role = row[0]
            # Map org roles to billing roles
            role_map = {
                "owner": "owner",
                "admin": "billing_admin",
                "billing_admin": "billing_admin",
                "member": "read_only",
                "viewer": "read_only",
            }
            billing_role = role_map.get(org_role, "read_only")
            return BillingActor(user_id=user_id, org_id=org_id, role=billing_role)

        # Default to read_only for authenticated users without explicit membership
        return BillingActor(user_id=user_id, org_id=org_id, role="read_only")


def require_billing_permission(
    actor: BillingActor,
    permission: str,
    request_id: Optional[str] = None,
) -> None:
    """
    Enforce billing permission check. Raises HTTPException if denied.

    Args:
        actor: The BillingActor representing the user
        permission: The permission to check
        request_id: Optional request_id for structured error response

    Raises:
        HTTPException 403 if permission denied
        ValueError if unknown permission
    """
    allowed_roles = BILLING_PERMISSION_MATRIX.get(permission)

    if allowed_roles is None:
        raise ValueError(f"Unknown billing permission: {permission}")

    if actor.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "BILLING_PERMISSION_DENIED",
                "message": f"Permission '{permission}' requires role: {', '.join(sorted(allowed_roles))}",
                "your_role": actor.role,
                "request_id": request_id,
            }
        )


def check_billing_permission(actor: BillingActor, permission: str) -> bool:
    """
    Check if actor has permission (non-throwing version).

    Returns True if allowed, False if denied.
    """
    allowed_roles = BILLING_PERMISSION_MATRIX.get(permission)
    if allowed_roles is None:
        return False
    return actor.role in allowed_roles

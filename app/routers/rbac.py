# app/routers/rbac.py
# Phase 73 — Enterprise RBAC Expansion

from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from typing import List, Tuple

from app.models.rbac import RbacSnapshot, Permission

router = APIRouter(prefix='/rbac', tags=['rbac'])


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

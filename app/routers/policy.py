# app/routers/policy.py
# Phase 70 — Controlled Enterprise Exposure
# Policy snapshot endpoint + role gating helpers

from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from typing import List

from app.config.policy_flags import ENTERPRISE_FLAGS
from app.models.policy import PolicySnapshot

router = APIRouter(prefix='/policy', tags=['policy'])


# NOTE: Replace this dependency with your real auth/role extraction logic.
async def get_user_roles() -> List[str]:
    """Get user roles from auth context. Replace with real implementation."""
    return ['user']


@router.get('/snapshot', response_model=PolicySnapshot)
async def get_policy_snapshot(roles: List[str] = Depends(get_user_roles)):
    """
    Get current policy snapshot including feature flags and user roles.

    Wiring-only: no persistence. Replace with tenant-aware policy store.
    """
    return PolicySnapshot(
        flags=ENTERPRISE_FLAGS,  # contract-first keys
        roles=roles,             # derived from auth provider
        updatedAtISO=datetime.now(timezone.utc).isoformat()
    )

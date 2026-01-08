# app/routers/onboarding.py
# Phase 72 — Enterprise Onboarding Hardening
# Policy-aware onboarding endpoints for enterprise admins

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import List

router = APIRouter(prefix='/onboarding', tags=['onboarding'])


# NOTE: Replace with real auth/role extraction logic
async def get_user_roles() -> List[str]:
    """Get user roles from auth context. Replace with real implementation."""
    return ['user']


class PolicyAckRequest(BaseModel):
    acknowledged: bool


class PolicyAckResponse(BaseModel):
    acknowledged: bool
    acknowledgedAtISO: str


@router.post('/enterprise-policy/ack', response_model=PolicyAckResponse)
async def acknowledge_enterprise_policy(
    payload: PolicyAckRequest,
    roles: List[str] = Depends(get_user_roles)
):
    """
    Acknowledge enterprise policy during onboarding.

    Wiring-only: must be enterprise_admin in real integration.
    Keep this endpoint internal/gated; no legal disclaimers changed.
    """
    return PolicyAckResponse(
        acknowledged=bool(payload.acknowledged),
        acknowledgedAtISO=datetime.now(timezone.utc).isoformat()
    )

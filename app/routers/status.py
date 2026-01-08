# app/routers/status.py
# Phase 75 — Enterprise SLA & Support Surfaces

from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timezone

router = APIRouter(prefix='/status', tags=['status'])


class StatusResponse(BaseModel):
    ok: bool
    checkedAtISO: str


@router.get('', response_model=StatusResponse)
async def status():
    """
    Get system status.

    Neutral endpoint. No SLA claims.
    """
    return StatusResponse(
        ok=True,
        checkedAtISO=datetime.now(timezone.utc).isoformat()
    )

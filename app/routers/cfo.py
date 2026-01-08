# app/routers/cfo.py
# Phase 62 — Contract-first CFO endpoints (backend kickoff bridge)

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Literal, Optional

router = APIRouter(tags=["cfo"])

InsightSeverity = Literal["low", "medium", "high"]

class RiskItem(BaseModel):
  id: str
  title: str
  severity: InsightSeverity

class ActionItem(BaseModel):
  id: str
  title: str
  rationale: str

class CfoSnapshot(BaseModel):
  as_of: str
  runway_days: Optional[int] = None
  cash_on_hand: Optional[float] = None
  burn_rate_monthly: Optional[float] = None
  top_risks: List[RiskItem]
  next_actions: List[ActionItem]

class CfoSnapshotResponse(BaseModel):
  generated_at: str
  snapshot: CfoSnapshot


def _now_iso() -> str:
  return datetime.utcnow().isoformat()


@router.get("/snapshot", response_model=CfoSnapshotResponse)
async def get_snapshot():
  now = _now_iso()
  return CfoSnapshotResponse(
    generated_at=now,
    snapshot=CfoSnapshot(
      as_of=now,
      runway_days=62,
      cash_on_hand=None,
      burn_rate_monthly=None,
      top_risks=[
        RiskItem(id="risk_001", title="Unreviewed high-severity anomaly", severity="high"),
        RiskItem(id="risk_002", title="Uncategorized transactions trending upward", severity="medium"),
      ],
      next_actions=[
        ActionItem(
          id="act_001",
          title="Review duplicate charge candidates",
          rationale="High confidence pattern match. Confirm and dispute if needed.",
        ),
        ActionItem(
          id="act_002",
          title="Set vendor rule for recurring spike vendor",
          rationale="Reduce future drift and improve categorization consistency.",
        ),
      ],
    ),
  )

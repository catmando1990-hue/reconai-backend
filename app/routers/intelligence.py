# app/routers/intelligence.py
# Phase 62 — Contract-first Intelligence endpoints (backend kickoff bridge)
#
# These endpoints intentionally return deterministic, backend-safe payloads that match
# the frontend contract layer. Business logic and persistence will be layered in later.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal, List

router = APIRouter(tags=["intelligence"])

AlertStatus = Literal["new", "in_review", "resolved"]
AlertKind = Literal["anomaly", "duplicate_charge", "vendor_risk", "compliance", "cash_flow"]

class AlertItem(BaseModel):
  id: str
  title: str
  summary: str
  kind: AlertKind
  status: AlertStatus
  confidence: float = Field(ge=0, le=1)
  created_at: str

class AlertsResponse(BaseModel):
  generated_at: str
  items: List[AlertItem]

WorkerTaskStatus = Literal["queued", "running", "blocked", "complete"]

class WorkerTask(BaseModel):
  id: str
  title: str
  summary: str
  status: WorkerTaskStatus
  confidence: float = Field(ge=0, le=1)
  created_at: str

class WorkerTasksResponse(BaseModel):
  generated_at: str
  items: List[WorkerTask]

InsightSeverity = Literal["low", "medium", "high"]
InsightType = Literal[
  "anomaly",
  "cash_flow",
  "category_drift",
  "duplicate_charge",
  "vendor_risk",
  "compliance",
  "opportunity",
]
InsightSource = Literal["rules", "ml", "llm", "hybrid"]

class Insight(BaseModel):
  id: str
  title: str
  summary: str
  type: InsightType
  severity: InsightSeverity
  confidence: float = Field(ge=0, le=1)
  created_at: str
  source: InsightSource

class InsightsSummaryResponse(BaseModel):
  generated_at: str
  items: List[Insight]


def _now_iso() -> str:
  return datetime.utcnow().isoformat()


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts():
  now = _now_iso()
  return AlertsResponse(
    generated_at=now,
    items=[
      AlertItem(
        id="alt_001",
        title="Potential duplicate charge requires review",
        summary="Two transactions appear similar in merchant and amount. Confirm if one is a duplicate.",
        kind="duplicate_charge",
        status="new",
        confidence=0.92,
        created_at=now,
      ),
      AlertItem(
        id="alt_002",
        title="Compliance signal: missing supporting note on flagged transaction",
        summary="A compliance-sensitive transaction is missing supporting context. Add documentation to reduce audit risk.",
        kind="compliance",
        status="in_review",
        confidence=0.78,
        created_at=now,
      ),
    ],
  )


@router.get("/worker/tasks", response_model=WorkerTasksResponse)
async def get_worker_tasks():
  now = _now_iso()
  return WorkerTasksResponse(
    generated_at=now,
    items=[
      WorkerTask(
        id="tsk_001",
        title="Review high-severity alerts (top 3)",
        summary="Triage alerts by confidence and severity label. Confirm or dismiss.",
        status="queued",
        confidence=0.88,
        created_at=now,
      ),
      WorkerTask(
        id="tsk_002",
        title="Propose vendor rule for recurring merchant",
        summary="Suggest a classification rule based on recent merchant behavior and history.",
        status="running",
        confidence=0.74,
        created_at=now,
      ),
    ],
  )


@router.get("/insights", response_model=InsightsSummaryResponse)
async def get_insights():
  now = _now_iso()
  return InsightsSummaryResponse(
    generated_at=now,
    items=[
      Insight(
        id="ins_001",
        title="Unusual spend spike at a recurring vendor",
        summary="Vendor spend increased vs baseline. Review for pricing change or scope creep.",
        type="anomaly",
        severity="medium",
        confidence=0.86,
        created_at=now,
        source="hybrid",
      ),
      Insight(
        id="ins_002",
        title="Potential duplicate charge detected",
        summary="Two transactions appear similar in merchant and amount. Confirm if one should be disputed.",
        type="duplicate_charge",
        severity="high",
        confidence=0.91,
        created_at=now,
        source="rules",
      ),
    ],
  )

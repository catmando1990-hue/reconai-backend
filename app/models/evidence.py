# app/models/evidence.py
# Phase 71 — Compliance evidence scaffolding models

from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

EvidenceType = Literal['log', 'config', 'policy', 'audit_event']


class EvidenceItem(BaseModel):
    id: str
    type: EvidenceType
    title: str
    createdAt: datetime
    # Human-readable description for auditors/CFOs; NOT advice.
    description: Optional[str] = None

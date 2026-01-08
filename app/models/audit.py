# app/models/audit.py
# Phase 67-69 — Audit event model for compliance tracking

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal


class AuditEvent(BaseModel):
    id: str
    timestamp: datetime
    source: Literal['system', 'user', 'ai']
    description: str
    confidence: Optional[float] = None

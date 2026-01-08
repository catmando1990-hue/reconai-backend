# app/routers/evidence.py
# Phase 71 — Compliance Evidence Mapping
# Read-only evidence scaffolding endpoints

from fastapi import APIRouter
from datetime import datetime, timezone
from typing import List

from app.models.evidence import EvidenceItem

router = APIRouter(prefix='/evidence', tags=['evidence'])


@router.get('/items', response_model=List[EvidenceItem])
async def list_evidence_items():
    """
    List available evidence items for compliance tracking.

    Wiring-only placeholder list. Replace with real evidence registry.
    No compliance claims - internal structure only.
    """
    return [
        EvidenceItem(
            id='ev_1',
            type='audit_event',
            title='Audit event stream available',
            createdAt=datetime.now(timezone.utc),
            description='Read-only audit stream for traceability. No compliance claims.'
        )
    ]

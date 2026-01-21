# app/intelligence/__init__.py
"""
Transaction Intelligence Module (Phase 1)

READ-ONLY overlay for transaction classification, duplicate detection,
and evidence generation. NO writes to source transaction tables.

CANONICAL LAWS ENFORCED:
- Backend is source of truth
- No polling, no background jobs
- Manual-run only
- Confidence < 0.85 must be flagged
- Immutable audit logging for classify runs
"""

from app.intelligence.engine import TransactionIntelligenceEngine
from app.intelligence.models import (
    ClassificationResult,
    EvidenceItem,
    DuplicateGroup,
    ClassifyRequest,
    ClassifyResponse,
    TransactionOverlayResponse,
)

__all__ = [
    "TransactionIntelligenceEngine",
    "ClassificationResult",
    "EvidenceItem",
    "DuplicateGroup",
    "ClassifyRequest",
    "ClassifyResponse",
    "TransactionOverlayResponse",
]

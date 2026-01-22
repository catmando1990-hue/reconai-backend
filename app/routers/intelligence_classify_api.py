# app/routers/intelligence_classify_api.py
"""
Transaction Intelligence API (Phase 1)

POST /api/intelligence/classify — Manual-only classification endpoint
GET /api/intelligence/transactions — Read-only overlay join

CANONICAL LAWS ENFORCED:
- Auth via get_current_context
- Org-scoped validation
- Structured error envelopes with request_id
- Immutable audit logging for classify runs
- No polling, no background jobs, no auto-run
- Confidence < 0.85 must be flagged
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.intelligence.engine import TransactionIntelligenceEngine
from app.intelligence.models import (
    ClassifyRequest,
    ClassifyResponse,
    TransactionOverlayResponse,
    Lifecycle,
    EvidenceMetadata,
    CoverageWindow,
)
from app.guardrails import (
    INTELLIGENCE_CONTRACT_VERSION,
    create_intelligence_lifecycle,
    create_evidence_metadata,
)
from app.services.audit_store import insert_audit_event, AuditEventInput


router = APIRouter(prefix="/api/intelligence", tags=["intelligence-classify"])

# Engine singleton (initialized on first use)
_engine: Optional[TransactionIntelligenceEngine] = None


def get_engine() -> TransactionIntelligenceEngine:
    """Get or create the intelligence engine."""
    global _engine
    if _engine is None:
        _engine = TransactionIntelligenceEngine(DB_PATH)
    return _engine


@router.post("/classify", response_model=ClassifyResponse)
async def classify_transactions(
    request: Request,
    body: ClassifyRequest,
    ctx: AuthContext = Depends(get_current_context),
    engine: TransactionIntelligenceEngine = Depends(get_engine),
):
    """
    POST /api/intelligence/classify

    Classify transactions and detect duplicates.
    Manual-run only — must be explicitly triggered by user action.

    Request body:
    {
        "transaction_ids": ["tx_001", "tx_002", ...]
    }

    Returns:
    - Classifications with confidence scores and evidence
    - Duplicate groups for review
    - Audit event ID for traceability

    CANONICAL LAWS:
    - NO polling or auto-triggers
    - NO writes to source transaction tables
    - Confidence < 0.85 flagged for review
    - Immutable audit log entry created
    """
    # Get request_id from middleware
    request_id = getattr(request.state, "request_id", str(uuid4()))

    # Validate org context
    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for classification",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        # Run classification (manual-only, non-destructive)
        classifications, duplicates, audit_id = engine.classify_transactions(
            org_id=org_id,
            user_id=user_id,
            transaction_ids=body.transaction_ids,
        )

        # Count flagged items
        flagged_count = sum(1 for c in classifications if c.requires_review)
        flagged_count += len(duplicates)  # All duplicates require review

        # Create immutable audit event
        audit_event = insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="INTELLIGENCE_CLASSIFY",
                entity_type="Transaction",
                entity_id=None,  # Bulk operation
                payload={
                    "transaction_ids": body.transaction_ids,
                    "classifications_count": len(classifications),
                    "duplicates_count": len(duplicates),
                    "flagged_for_review": flagged_count,
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )

        # Compute lifecycle status
        if len(classifications) == 0 and len(duplicates) == 0:
            lifecycle = Lifecycle(status="no_data", reason_code="NO_TRANSACTIONS_PROCESSED")
        elif flagged_count == len(classifications) + len(duplicates):
            lifecycle = Lifecycle(status="partial", reason_code="ALL_REQUIRE_REVIEW")
        elif flagged_count > 0:
            lifecycle = Lifecycle(status="partial", reason_code="SOME_REQUIRE_REVIEW")
        else:
            lifecycle = Lifecycle(status="success", reason_code=None)

        # Compute average confidence for evidence metadata
        all_confidences = [c.confidence for c in classifications]
        all_confidences.extend([d.confidence for d in duplicates])
        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0

        # Build evidence metadata
        evidence_meta = EvidenceMetadata(
            sources=["transaction_classifications", "duplicate_detection"],
            coverage_window=CoverageWindow(start=None, end=None),
            evaluated_at=now,
            confidence_score=avg_confidence,
        )

        return ClassifyResponse(
            ok=True,
            lifecycle=lifecycle,
            evidence=evidence_meta,
            request_id=request_id,
            classified_at=now,
            classifications=classifications,
            duplicates=duplicates,
            total_processed=len(body.transaction_ids),
            flagged_for_review=flagged_count,
            audit_event_id=audit_event.id,
            guardrails={
                "confidence_threshold": 0.85,
                "writes_to_transactions": False,
                "advisory_only": False,  # Phase 1 writes to separate tables
                "manual_run_only": True,
            },
        )

    except Exception as e:
        # Log error in audit trail
        insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="INTELLIGENCE_CLASSIFY_ERROR",
                entity_type="Transaction",
                entity_id=None,
                payload={
                    "error": str(e),
                    "transaction_ids": body.transaction_ids,
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "CLASSIFICATION_FAILED",
                "message": f"Classification failed: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/transactions", response_model=TransactionOverlayResponse)
async def get_transactions_with_overlay(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: TransactionIntelligenceEngine = Depends(get_engine),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    only_flagged: bool = Query(default=False),
):
    """
    GET /api/intelligence/transactions

    Read-only overlay join of transactions with their classifications.
    Returns transactions with classification data and duplicate flags.

    Query params:
    - limit: Max results (1-200, default 50)
    - offset: Pagination offset
    - only_flagged: If true, only return items requiring review

    CANONICAL LAWS:
    - Read-only: no mutations
    - Source table (mvp_transactions) is never modified
    - Classification data comes from overlay tables
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    # Validate org context
    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required",
                "request_id": request_id,
            },
        )

    now = datetime.utcnow().isoformat()

    try:
        transactions, total = engine.get_transactions_with_overlay(
            org_id=org_id,
            limit=limit,
            offset=offset,
            only_flagged=only_flagged,
        )

        # Calculate stats
        classified_count = sum(1 for t in transactions if t.has_classification)
        flagged_count = sum(
            1 for t in transactions
            if (t.classification and t.classification.requires_review)
            or t.duplicate_group is not None
        )

        # Compute lifecycle status
        if total == 0:
            lifecycle = Lifecycle(status="no_data", reason_code="NO_TRANSACTIONS_FOUND")
        elif classified_count == 0:
            lifecycle = Lifecycle(status="partial", reason_code="NO_CLASSIFICATIONS")
        elif flagged_count > 0:
            lifecycle = Lifecycle(status="partial", reason_code="SOME_FLAGGED")
        else:
            lifecycle = Lifecycle(status="success", reason_code=None)

        # Build evidence metadata
        evidence_meta = EvidenceMetadata(
            sources=["mvp_transactions", "transaction_classifications", "transaction_evidence"],
            coverage_window=CoverageWindow(start=None, end=None),
            evaluated_at=now,
            confidence_score=0.0,  # Read-only overlay, no aggregate confidence
        )

        return TransactionOverlayResponse(
            ok=True,
            lifecycle=lifecycle,
            evidence=evidence_meta,
            request_id=request_id,
            generated_at=now,
            transactions=transactions,
            total_count=total,
            classified_count=classified_count,
            unclassified_count=len(transactions) - classified_count,
            flagged_count=flagged_count,
            guardrails={
                "read_only": True,
                "source_table": "mvp_transactions",
                "overlay_tables": ["transaction_classifications", "transaction_evidence"],
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "QUERY_FAILED",
                "message": f"Failed to fetch transactions: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/stats")
async def get_classification_stats(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: TransactionIntelligenceEngine = Depends(get_engine),
):
    """
    GET /api/intelligence/stats

    Get classification statistics for the organization.
    Read-only endpoint.
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required",
                "request_id": request_id,
            },
        )

    now = datetime.utcnow().isoformat()

    try:
        stats = engine.get_classification_stats(org_id)

        # Compute lifecycle status
        has_data = stats.get("total_transactions", 0) > 0
        if not has_data:
            lifecycle_dict = create_intelligence_lifecycle("no_data", "NO_STATS_DATA")
        else:
            lifecycle_dict = create_intelligence_lifecycle("success")

        # Build evidence metadata
        evidence_dict = create_evidence_metadata(
            sources=["transaction_classifications", "transaction_evidence"],
            evaluated_at=now,
            confidence_score=0.0,  # Stats endpoint, no aggregate confidence
        )

        return {
            "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
            "lifecycle": lifecycle_dict,  # ALWAYS present
            "evidence": evidence_dict,  # ALWAYS present
            "ok": True,
            "request_id": request_id,
            "generated_at": now,
            "stats": stats,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "STATS_FAILED",
                "message": f"Failed to get stats: {str(e)}",
                "request_id": request_id,
            },
        )

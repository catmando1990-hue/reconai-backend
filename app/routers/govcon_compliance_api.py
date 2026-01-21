# app/routers/govcon_compliance_api.py
"""
GovCon / DCAA Compliance API (Phase 2)

GET /api/govcon/transactions — Read-only overlay with compliance classifications
POST /api/govcon/export — Manual-only export preview generation

CANONICAL LAWS ENFORCED:
- Auth via get_current_context
- Org-scoped enforcement
- Structured error envelopes with request_id
- Immutable audit logging for exports
- No auto-export, no background jobs, no polling
- Export must be explicitly user-triggered
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.entitlements.tiers import require_govcon_entitlement
from app.govcon.engine import GovConComplianceEngine
from app.govcon.models import (
    GovConTransactionsResponse,
    ExportPreviewResponse,
    CostPoolType,
    AllowabilityStatus,
)
from app.services.audit_store import insert_audit_event, AuditEventInput


router = APIRouter(prefix="/api/govcon", tags=["govcon-compliance"])

# Engine singleton (initialized on first use)
_engine: Optional[GovConComplianceEngine] = None


def get_engine() -> GovConComplianceEngine:
    """Get or create the GovCon compliance engine."""
    global _engine
    if _engine is None:
        _engine = GovConComplianceEngine(DB_PATH)
    return _engine


async def require_govcon_access(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """Dependency that enforces GovCon entitlement."""
    require_govcon_entitlement(ctx["tier"], request=request)
    return ctx


class ClassifyRequest(BaseModel):
    """Request to classify transactions for GovCon compliance."""

    transaction_ids: List[str] = Field(
        min_length=1,
        max_length=100,
        description="List of transaction IDs to classify"
    )


class ClassifyResponse(BaseModel):
    """Response from GovCon classification endpoint."""

    ok: bool
    request_id: str
    classified_at: str
    classifications_count: int
    allowable_count: int
    unallowable_count: int
    pending_review_count: int
    audit_event_id: str


class ExportRequest(BaseModel):
    """Request to generate export preview (manual-only)."""

    transaction_ids: Optional[List[str]] = Field(
        default=None,
        max_length=500,
        description="Optional list of specific transaction IDs to export"
    )


@router.post("/classify", response_model=ClassifyResponse)
async def classify_transactions(
    request: Request,
    body: ClassifyRequest,
    ctx: AuthContext = Depends(require_govcon_access),
    engine: GovConComplianceEngine = Depends(get_engine),
):
    """
    POST /api/govcon/classify

    Classify transactions for DCAA compliance.
    Manual-run only — must be explicitly triggered by user action.

    Determines:
    - Allowability status per FAR 31.201
    - Cost pool attribution per CAS 418
    - Links to Phase 1 intelligence classifications

    Returns:
    - Classification counts and audit event ID

    CANONICAL LAWS:
    - NO polling or auto-triggers
    - NO writes to source transaction tables
    - Evidence chain created for each classification
    - Immutable audit log entry created
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for GovCon classification",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        classifications, audit_id = engine.classify_transactions(
            org_id=org_id,
            user_id=user_id,
            transaction_ids=body.transaction_ids,
        )

        # Count by allowability
        allowable_count = sum(1 for c in classifications if c.allowability == "allowable")
        unallowable_count = sum(1 for c in classifications if c.allowability == "unallowable")
        pending_count = sum(1 for c in classifications if c.allowability == "pending_review")

        # Create immutable audit event
        audit_event = insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="GOVCON_CLASSIFY",
                entity_type="Transaction",
                entity_id=None,
                payload={
                    "transaction_ids": body.transaction_ids,
                    "classifications_count": len(classifications),
                    "allowable_count": allowable_count,
                    "unallowable_count": unallowable_count,
                    "pending_review_count": pending_count,
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )

        return ClassifyResponse(
            ok=True,
            request_id=request_id,
            classified_at=now,
            classifications_count=len(classifications),
            allowable_count=allowable_count,
            unallowable_count=unallowable_count,
            pending_review_count=pending_count,
            audit_event_id=audit_event.id,
        )

    except Exception as e:
        insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="GOVCON_CLASSIFY_ERROR",
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
                "error": "GOVCON_CLASSIFICATION_FAILED",
                "message": f"GovCon classification failed: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/transactions", response_model=GovConTransactionsResponse)
async def get_transactions_with_overlay(
    request: Request,
    ctx: AuthContext = Depends(require_govcon_access),
    engine: GovConComplianceEngine = Depends(get_engine),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    allowability: Optional[AllowabilityStatus] = Query(default=None),
    cost_pool: Optional[CostPoolType] = Query(default=None),
    only_pending_review: bool = Query(default=False),
):
    """
    GET /api/govcon/transactions

    Read-only overlay join of transactions with GovCon compliance classifications.
    Returns transactions with allowability, cost pool, and evidence chain data.

    Query params:
    - limit: Max results (1-200, default 50)
    - offset: Pagination offset
    - allowability: Filter by allowability status
    - cost_pool: Filter by cost pool
    - only_pending_review: If true, only return items requiring review

    CANONICAL LAWS:
    - Read-only: no mutations
    - Source table (mvp_transactions) is never modified
    - Classification data comes from overlay tables
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
        transactions, total = engine.get_transactions_with_overlay(
            org_id=org_id,
            limit=limit,
            offset=offset,
            allowability_filter=allowability,
            cost_pool_filter=cost_pool,
            only_pending_review=only_pending_review,
        )

        # Calculate stats
        classified_count = sum(1 for t in transactions if t.has_govcon_classification)
        allowable_count = sum(
            1 for t in transactions
            if t.govcon_classification and t.govcon_classification.allowability == "allowable"
        )
        unallowable_count = sum(
            1 for t in transactions
            if t.govcon_classification and t.govcon_classification.allowability == "unallowable"
        )
        pending_count = sum(1 for t in transactions if t.requires_review)

        return GovConTransactionsResponse(
            ok=True,
            request_id=request_id,
            generated_at=now,
            transactions=transactions,
            total_count=total,
            classified_count=classified_count,
            allowable_count=allowable_count,
            unallowable_count=unallowable_count,
            pending_review_count=pending_count,
            guardrails={
                "read_only": True,
                "source_table": "mvp_transactions",
                "overlay_tables": ["govcon_classifications", "govcon_evidence_chain"],
                "dcaa_compliant": True,
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


@router.post("/export", response_model=ExportPreviewResponse)
async def generate_export_preview(
    request: Request,
    body: ExportRequest,
    ctx: AuthContext = Depends(require_govcon_access),
    engine: GovConComplianceEngine = Depends(get_engine),
):
    """
    POST /api/govcon/export

    Generate export preview for DCAA submission.
    MANUAL-ONLY — must be explicitly triggered by user action.
    Returns preview payload; does NOT auto-export.

    Returns:
    - Preview of exportable transactions
    - Summary statistics
    - Blocking issues (if any)
    - Audit event ID for traceability

    CANONICAL LAWS:
    - NO auto-export
    - NO background jobs
    - NO polling
    - Export must be explicitly user-triggered
    - Immutable audit log entry created
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for export",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        preview, summary, blocking_issues = engine.generate_export_preview(
            org_id=org_id,
            user_id=user_id,
            transaction_ids=body.transaction_ids,
        )

        export_ready = len(blocking_issues) == 0 and len(preview) > 0

        # Create immutable audit event
        audit_event = insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="GOVCON_EXPORT_PREVIEW",
                entity_type="Export",
                entity_id=None,
                payload={
                    "transaction_count": len(preview),
                    "export_ready": export_ready,
                    "blocking_issues_count": len(blocking_issues),
                    "summary": summary,
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )

        return ExportPreviewResponse(
            ok=True,
            request_id=request_id,
            generated_at=now,
            preview=preview,
            summary=summary,
            export_ready=export_ready,
            blocking_issues=blocking_issues[:10],  # Limit to first 10 issues
            audit_event_id=audit_event.id,
            guardrails={
                "auto_export": False,
                "manual_trigger_required": True,
                "dcaa_compliant": True,
                "immutable_audit": True,
            },
        )

    except Exception as e:
        insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="GOVCON_EXPORT_ERROR",
                entity_type="Export",
                entity_id=None,
                payload={
                    "error": str(e),
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "EXPORT_PREVIEW_FAILED",
                "message": f"Export preview generation failed: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/stats")
async def get_compliance_stats(
    request: Request,
    ctx: AuthContext = Depends(require_govcon_access),
    engine: GovConComplianceEngine = Depends(get_engine),
):
    """
    GET /api/govcon/stats

    Get GovCon compliance statistics for the organization.
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

    try:
        # Get all transactions to compute stats
        transactions, total = engine.get_transactions_with_overlay(
            org_id=org_id,
            limit=1000,
            offset=0,
        )

        classified_count = sum(1 for t in transactions if t.has_govcon_classification)
        dcaa_compliant = sum(1 for t in transactions if t.dcaa_compliant)
        pending_review = sum(1 for t in transactions if t.requires_review)

        # Count by allowability
        by_allowability = {}
        for t in transactions:
            if t.govcon_classification:
                status = t.govcon_classification.allowability
                by_allowability[status] = by_allowability.get(status, 0) + 1

        # Count by cost pool
        by_cost_pool = {}
        for t in transactions:
            if t.govcon_classification:
                pool = t.govcon_classification.cost_pool
                by_cost_pool[pool] = by_cost_pool.get(pool, 0) + 1

        return {
            "ok": True,
            "request_id": request_id,
            "generated_at": datetime.utcnow().isoformat(),
            "stats": {
                "total_transactions": total,
                "classified_count": classified_count,
                "unclassified_count": total - classified_count,
                "dcaa_compliant_count": dcaa_compliant,
                "pending_review_count": pending_review,
                "by_allowability": by_allowability,
                "by_cost_pool": by_cost_pool,
            },
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

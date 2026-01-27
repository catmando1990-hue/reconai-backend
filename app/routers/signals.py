"""
Signals API - Anomaly detection and risk signals.

P1 FIX: All signal responses now include explicit mode labeling.
When DEMO_MODE is True, responses include { "mode": "demo" } to indicate
that the data is not from real detection algorithms.

Phase 5.5: GET /api/signals/p1 - Advisory-only endpoint backed by intelligence_signals
Phase 6: POST /api/signals/detect - Manual exception detection execution

CANONICAL LAWS:
- Backend is source of truth
- No demo data presented as real
- Explicit lifecycle clarity
- Deterministic detection only (no AI inference)
- Manual execution only (no auto-run)
"""
import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.auth_context import get_current_context, get_current_organization_id

router = APIRouter(prefix="/api")


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())

# P1 FIX: Demo mode flag - set to False when real signal detection is implemented
DEMO_MODE = True


@router.get("/signals")
def list_signals(ctx=Depends(get_current_context)):
    """
    List detected signals/anomalies.

    P1 FIX: Response includes "mode" field to indicate data provenance:
    - "demo": Hardcoded sample data for demonstration
    - "live": Real detection from actual transaction data
    """
    if DEMO_MODE:
        return {
            "mode": "demo",
            "signals": [
                {
                    "id": "sig_dup_1",
                    "type": "duplicate_charge",
                    "severity": "warning",
                    "entity": "transaction",
                    "entity_id": "tx_1",
                    "message": "Potential duplicate charge detected",
                    "confidence": 0.75,  # Below 0.85 threshold - won't display by default
                    "created_at": "2026-01-12T10:15:00Z"
                }
            ],
            "disclaimer": "Demo mode: These signals are sample data for demonstration purposes only."
        }

    # TODO: Implement real signal detection
    return {
        "mode": "live",
        "signals": [],
        "disclaimer": None
    }


@router.get("/signals/{signal_id}/evidence")
def signal_evidence(signal_id: str, ctx=Depends(get_current_context)):
    """
    Get evidence/explanation for a specific signal.

    P1 FIX: Response includes "mode" field for provenance transparency.
    """
    if DEMO_MODE:
        return {
            "mode": "demo",
            "signal_id": signal_id,
            "rule": "same_merchant + same_amount + posted_within_48h",
            "entity_id": "tx_1",
            "transactions": [
                {"id": "tx_1", "date": "2026-01-12", "merchant": "Demo Vendor", "amount": 99.99},
                {"id": "tx_2", "date": "2026-01-12", "merchant": "Demo Vendor", "amount": 99.99}
            ],
            "disclaimer": "Demo mode: This evidence is sample data for demonstration purposes only."
        }

    # TODO: Implement real evidence retrieval
    return {
        "mode": "live",
        "signal_id": signal_id,
        "rule": None,
        "entity_id": None,
        "transactions": [],
        "disclaimer": None
    }


# =============================================================================
# PHASE 5.5: P1 ENDPOINT — GET /api/signals/p1 (ADVISORY-ONLY)
# =============================================================================
# READ-ONLY advisory endpoint backed by intelligence_signals table
# - Returns signals with confidence >= min_confidence
# - Default min_confidence = 0.85
# - Does NOT generate signals
# - Does NOT infer or enrich beyond stored fields
# - Org-isolated via organization_id filter

@router.get("/signals/p1", tags=["signals", "p1"])
async def get_signals_p1(
    request: Request,
    min_confidence: float = 0.85,
    organization_id: str = Depends(get_current_organization_id)
):
    """
    P1 Endpoint: List intelligence signals (advisory-only).

    Phase 5.5 — ADVISORY-ONLY

    Query Parameters:
        min_confidence: Minimum confidence threshold (default: 0.85)

    Behavior:
        - Returns only signals with confidence >= min_confidence
        - Does NOT generate signals
        - Does NOT infer or enrich beyond stored fields
        - Advisory output only (no actions, no mutations)

    Returns:
        items: List of signals meeting confidence threshold
        request_id: UUID for request tracing
        advisory: true (always)
    """
    from app.db import get_db_connection

    request_id = _get_request_id(request)

    # Validate min_confidence bounds
    if min_confidence < 0.0 or min_confidence > 1.0:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_confidence_threshold",
                "detail": "min_confidence must be between 0.0 and 1.0",
                "request_id": request_id,
                "advisory": True
            }
        )

    sql = """
        SELECT
            signal_id,
            title,
            description,
            confidence,
            evidence_ref,
            created_at
        FROM intelligence_signals
        WHERE organization_id = ?
          AND confidence >= ?
        ORDER BY confidence DESC, created_at DESC
    """

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (organization_id, min_confidence))
        rows = cursor.fetchall()
        conn.close()

        items = []
        for row in rows:
            items.append({
                "signal_id": row[0],
                "title": row[1],
                "description": row[2],
                "confidence": row[3],
                "evidence_ref": row[4],
                "created_at": row[5]
            })

        return {
            "items": items,
            "request_id": request_id,
            "advisory": True
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "signals_fetch_failed",
                "detail": str(e),
                "request_id": request_id,
                "advisory": True
            }
        )


# =============================================================================
# PHASE 6.2: POST /api/signals/detect — MANUAL EXCEPTION DETECTION
# =============================================================================
# Executes deterministic exception detection rules and APPENDS to intelligence_signals
# - MANUAL execution only (invoked explicitly, NOT on request paths)
# - Deterministic rules only (confidence = 1.0)
# - APPEND-ONLY writes (no dedup, no clear)
# - Audit logging REQUIRED (exactly once per run)

class DetectRequest(BaseModel):
    """Request body for detection endpoint."""
    threshold: float = 10000.0
    period_start: Optional[str] = None  # YYYY-MM-DD, required for E4
    period_end: Optional[str] = None    # YYYY-MM-DD, required for E4
    rules: Optional[List[str]] = None   # E1-E6, None = all


@router.post("/signals/detect", tags=["signals", "detection"])
async def run_detection(
    request: Request,
    body: DetectRequest = DetectRequest(),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Phase 6.2 Endpoint: Execute deterministic exception detection.

    MANUAL EXECUTION ONLY — invoked explicitly (admin/tooling), NOT on request paths.
    One invocation = one scan + one batch insert.

    Request Body:
        threshold: Amount threshold for E3 (default: 10000)
        period_start: Period start for E4 (YYYY-MM-DD). REQUIRED for E4.
        period_end: Period end for E4 (YYYY-MM-DD). REQUIRED for E4.
        rules: List of rule IDs to run (None = all E1-E6)

    Available Rules (E1-E6 Taxonomy):
        - E1: Uncategorized Transaction (category IS NULL OR empty)
        - E2: Duplicate Transaction (exact match on amount, date, account_id, name)
        - E3: Amount Threshold Breach (ABS(amount) >= threshold)
        - E4: Out-of-Period Posting (date NOT BETWEEN period_start AND period_end)
        - E5: Missing Counterparty (no linked vendor or customer)
        - E6: Negative Balance Event (running balance < 0)

    Returns:
        organization_id: Organization scanned
        request_id: UUID for request tracing
        signals_detected: Total signals found
        signals_inserted: Signals successfully inserted (APPEND-ONLY)
        signals_by_rule: Breakdown by rule ID
        threshold_used: Threshold value used for E3
        period_start/period_end: Period used for E4
        errors: List of any errors encountered
        executed_at: ISO timestamp

    APPEND-ONLY: Does NOT dedupe. Does NOT clear existing signals.
    """
    from app.services.exception_detection import run_exception_detection

    request_id = _get_request_id(request)

    # Execute detection
    try:
        result = run_exception_detection(
            organization_id=organization_id,
            threshold=body.threshold,
            period_start=body.period_start,
            period_end=body.period_end,
            request_id=request_id,
            rules=body.rules
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "detection_execution_failed",
                "detail": str(e),
                "request_id": request_id
            }
        )

    # Note: Audit logging is handled internally by run_exception_detection

    return {
        "organization_id": result.organization_id,
        "request_id": result.request_id,
        "signals_detected": result.signals_detected,
        "signals_inserted": result.signals_inserted,
        "signals_by_rule": result.signals_by_rule,
        "threshold_used": result.threshold_used,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "errors": result.errors,
        "executed_at": result.executed_at
    }


@router.get("/signals/rules", tags=["signals", "detection"])
async def list_detection_rules():
    """
    List available exception detection rules (E1-E6 taxonomy).

    Returns rule IDs and their titles.
    """
    from app.services.exception_detection import get_detection_rules

    rules = get_detection_rules()

    return {
        "rules": [
            {"rule_id": rule_id, "title": title}
            for rule_id, title in rules.items()
        ],
        "total": len(rules),
        "ruleset_version": "E1-E6 v1"
    }

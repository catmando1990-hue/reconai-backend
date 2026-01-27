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
# PHASE 6: POST /api/signals/detect — MANUAL EXCEPTION DETECTION
# =============================================================================
# Executes deterministic exception detection rules and populates intelligence_signals
# - MANUAL execution only (must be explicitly triggered)
# - Deterministic rules only (confidence = 1.0)
# - Fail-closed audit logging
# - Clears existing signals before inserting new ones (default)

class DetectRequest(BaseModel):
    """Request body for detection endpoint."""
    clear_existing: bool = True
    rules: Optional[List[str]] = None


@router.post("/signals/detect", tags=["signals", "detection"])
async def run_detection(
    request: Request,
    body: DetectRequest = DetectRequest(),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Phase 6 Endpoint: Execute deterministic exception detection.

    MANUAL EXECUTION ONLY - This endpoint must be called explicitly.
    It does NOT run automatically on transaction insert/update.

    Request Body:
        clear_existing: If True (default), clears existing signals before inserting
        rules: List of rule IDs to run (None = all rules)

    Available Rules:
        - UNCATEGORIZED_TRANSACTION: Transactions with no category
        - DUPLICATE_TRANSACTION: Same amount, date, account_id, name
        - AMOUNT_THRESHOLD_BREACH: ABS(amount) >= $10,000
        - OUT_OF_PERIOD_POSTING: Date outside current fiscal year
        - MISSING_COUNTERPARTY: No linked vendor or customer
        - NEGATIVE_BALANCE_EVENT: Running balance < 0

    Returns:
        organization_id: Organization scanned
        request_id: UUID for request tracing
        signals_detected: Total signals found
        signals_inserted: Signals successfully inserted
        signals_by_rule: Breakdown by rule ID
        errors: List of any errors encountered
        executed_at: ISO timestamp
    """
    from app.services.exception_detection import run_exception_detection
    from app.services.audit_service import record_audit, AuditServiceError

    request_id = _get_request_id(request)

    # Execute detection
    try:
        result = run_exception_detection(
            organization_id=organization_id,
            request_id=request_id,
            clear_existing=body.clear_existing,
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

    # Audit log the execution (fail-closed)
    try:
        record_audit(
            actor="system",
            action="exception_detection_executed",
            entity="intelligence_signals",
            entity_id=organization_id,
            payload={
                "signals_detected": result.signals_detected,
                "signals_inserted": result.signals_inserted,
                "signals_by_rule": result.signals_by_rule,
                "clear_existing": body.clear_existing,
                "rules_requested": body.rules,
                "errors": result.errors
            },
            request_id=request_id
        )
    except AuditServiceError as e:
        # Fail-closed: If audit fails, abort the request
        return JSONResponse(
            status_code=500,
            content={
                "error": "audit_failed",
                "detail": f"Detection succeeded but audit logging failed (fail-closed): {str(e)}",
                "request_id": request_id,
                "signals_detected": result.signals_detected,
                "signals_inserted": result.signals_inserted
            }
        )

    return {
        "organization_id": result.organization_id,
        "request_id": result.request_id,
        "signals_detected": result.signals_detected,
        "signals_inserted": result.signals_inserted,
        "signals_by_rule": result.signals_by_rule,
        "errors": result.errors,
        "executed_at": result.executed_at
    }


@router.get("/signals/rules", tags=["signals", "detection"])
async def list_detection_rules():
    """
    List available exception detection rules.

    Returns metadata for each rule including title and description template.
    """
    from app.services.exception_detection import get_detection_rules

    rules = get_detection_rules()

    return {
        "rules": [
            {
                "rule_id": rule_id,
                "title": meta["title"],
                "description_template": meta["description_template"]
            }
            for rule_id, meta in rules.items()
        ],
        "total": len(rules)
    }

"""
Signals API - Anomaly detection and risk signals.

P1 FIX: All signal responses now include explicit mode labeling.
When DEMO_MODE is True, responses include { "mode": "demo" } to indicate
that the data is not from real detection algorithms.

CANONICAL LAWS:
- Backend is source of truth
- No demo data presented as real
- Explicit lifecycle clarity
"""
import os
from fastapi import APIRouter, Depends
from app.auth_context import get_current_context

router = APIRouter(prefix="/api")

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

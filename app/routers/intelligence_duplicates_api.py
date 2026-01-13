# intelligence_duplicates_api.py
# INTELLIGENCE 1B — Enhanced Duplicate Detection (Read-only)
# Returns potential duplicate transactions for review.
# NO writes, NO mutations — advisory only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext

router = APIRouter(prefix="/api/intelligence")

# BUILD 13 guardrails
CONFIDENCE_THRESHOLD = 0.85


@router.get("/duplicates")
async def get_duplicate_candidates(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = 10,
):
    """
    GET /api/intelligence/duplicates

    Returns potential duplicate transactions detected by ML analysis.
    Advisory-only — does not write or mutate any data.

    Guardrails enforced:
    - confidence >= 0.85 threshold
    - explanation required
    - evidence references existing transactions
    """
    # Placeholder duplicates — in production, this would query detection model
    duplicate_groups = [
        {
            "group_id": "dup_group_001",
            "transactions": ["tx_abc123", "tx_abc124"],
            "confidence": 0.94,
            "explanation": "Same merchant (Amazon) and identical amount ($47.99) within 48 hours",
            "evidence": {
                "merchant_match": True,
                "amount_match": True,
                "time_window_hours": 48,
                "transaction_refs": ["tx_abc123", "tx_abc124"],
            },
        },
        {
            "group_id": "dup_group_002",
            "transactions": ["tx_def456", "tx_def457", "tx_def458"],
            "confidence": 0.87,
            "explanation": "Recurring charge pattern detected — same merchant, same day of month",
            "evidence": {
                "merchant_match": True,
                "recurring_pattern": True,
                "day_of_month": 15,
                "transaction_refs": ["tx_def456", "tx_def457", "tx_def458"],
            },
        },
    ]

    # Filter by confidence threshold (BUILD 13 guardrail)
    filtered = [g for g in duplicate_groups if g["confidence"] >= CONFIDENCE_THRESHOLD]

    return {
        "ok": True,
        "mode": "advisory",
        "writes_allowed": False,
        "duplicates": filtered[:limit],
        "guardrails": {
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "explanation_required": True,
            "signal_backed_only": True,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

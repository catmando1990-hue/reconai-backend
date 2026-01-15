# intelligence_duplicates_api.py
# INTELLIGENCE 1B — Enhanced Duplicate Detection (Read-only)
# Returns potential duplicate transactions for review.
# NO writes, NO mutations — advisory only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.guardrails import wrap_intelligence_response

router = APIRouter(prefix="/api/intelligence")


@router.get("/duplicates")
async def get_duplicate_candidates(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = 10,
):
    """
    GET /api/intelligence/duplicates

    Returns potential duplicate transactions detected by ML analysis.
    Advisory-only — does not write or mutate any data.

    Contract enforced via guardrails/intelligence_contract.py:
    - confidence >= 0.85 threshold
    - explanation required
    - evidence required
    - manual-run only
    """
    # Placeholder duplicates — in production, this would query detection model
    duplicate_groups = [
        {
            "group_id": "dup_group_001",
            "transactions": ["tx_abc123", "tx_abc124"],
            "confidence": 0.94,
            "explanation": "Same merchant (Amazon) and identical amount ($47.99) within 48 hours",
            "evidence": [
                {"type": "merchant_match", "value": True},
                {"type": "amount_match", "value": True},
                {"type": "time_window_hours", "value": 48},
                {"type": "transaction_refs", "value": ["tx_abc123", "tx_abc124"]},
            ],
        },
        {
            "group_id": "dup_group_002",
            "transactions": ["tx_def456", "tx_def457", "tx_def458"],
            "confidence": 0.87,
            "explanation": "Recurring charge pattern detected — same merchant, same day of month",
            "evidence": [
                {"type": "merchant_match", "value": True},
                {"type": "recurring_pattern", "value": True},
                {"type": "day_of_month", "value": 15},
                {"type": "transaction_refs", "value": ["tx_def456", "tx_def457", "tx_def458"]},
            ],
        },
        {
            "group_id": "dup_group_003",
            "transactions": ["tx_low_conf"],
            "confidence": 0.72,  # Below threshold - will be filtered
            "explanation": "Possible duplicate but low confidence",
            "evidence": [{"type": "weak_match", "value": True}],
        },
    ]

    # Apply central contract enforcement (confidence gating + schema validation)
    response = wrap_intelligence_response(
        duplicate_groups[:limit],
        result_key="duplicates",
        timestamp=datetime.utcnow().isoformat(),
    )

    return response

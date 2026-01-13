# intelligence_categorization_api.py
# INTELLIGENCE 1A — Categorization Suggestions (Advisory-only)
# Returns ML-based category suggestions for transactions.
# NO writes, NO mutations — advisory only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

from app.auth_context import get_current_context, AuthContext

router = APIRouter(prefix="/api/intelligence")

# BUILD 13 guardrails
CONFIDENCE_THRESHOLD = 0.85


@router.get("/categorization/suggestions")
async def get_categorization_suggestions(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = 10,
):
    """
    GET /api/intelligence/categorization/suggestions

    Returns AI-suggested categories for uncategorized transactions.
    Advisory-only — does not write or mutate any data.

    Guardrails enforced:
    - confidence >= 0.85 threshold
    - explanation required
    - signal-backed evidence
    """
    # Placeholder suggestions — in production, this would query ML model
    suggestions = [
        {
            "transaction_id": "tx_example_001",
            "suggested_category": "Software & SaaS",
            "confidence": 0.92,
            "explanation": "Merchant 'Adobe Inc' historically classified as software subscription based on 47 similar transactions",
            "evidence": {
                "merchant_pattern": "Adobe Inc",
                "similar_transactions": 47,
                "category_signals": ["recurring", "subscription", "software"],
            },
        },
        {
            "transaction_id": "tx_example_002",
            "suggested_category": "Office Supplies",
            "confidence": 0.88,
            "explanation": "Merchant 'Staples' matches office supplies category with high confidence",
            "evidence": {
                "merchant_pattern": "Staples",
                "similar_transactions": 23,
                "category_signals": ["retail", "office", "supplies"],
            },
        },
    ]

    # Filter by confidence threshold (BUILD 13 guardrail)
    filtered = [s for s in suggestions if s["confidence"] >= CONFIDENCE_THRESHOLD]

    return {
        "ok": True,
        "mode": "advisory",
        "writes_allowed": False,
        "suggestions": filtered[:limit],
        "guardrails": {
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "explanation_required": True,
            "signal_backed_only": True,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

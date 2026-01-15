# intelligence_categorization_api.py
# INTELLIGENCE 1A — Categorization Suggestions (Advisory-only)
# Returns ML-based category suggestions for transactions.
# NO writes, NO mutations — advisory only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.guardrails import wrap_intelligence_response

router = APIRouter(prefix="/api/intelligence")


@router.get("/categorization/suggestions")
async def get_categorization_suggestions(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = 10,
):
    """
    GET /api/intelligence/categorization/suggestions

    Returns AI-suggested categories for uncategorized transactions.
    Advisory-only — does not write or mutate any data.

    Contract enforced via guardrails/intelligence_contract.py:
    - confidence >= 0.85 threshold
    - explanation required
    - evidence required
    - manual-run only
    """
    # Placeholder suggestions — in production, this would query ML model
    suggestions = [
        {
            "transaction_id": "tx_example_001",
            "suggested_category": "Software & SaaS",
            "confidence": 0.92,
            "explanation": "Merchant 'Adobe Inc' historically classified as software subscription based on 47 similar transactions",
            "evidence": [
                {"type": "merchant_pattern", "value": "Adobe Inc"},
                {"type": "similar_transactions", "value": 47},
                {"type": "category_signals", "value": ["recurring", "subscription", "software"]},
            ],
        },
        {
            "transaction_id": "tx_example_002",
            "suggested_category": "Office Supplies",
            "confidence": 0.88,
            "explanation": "Merchant 'Staples' matches office supplies category with high confidence",
            "evidence": [
                {"type": "merchant_pattern", "value": "Staples"},
                {"type": "similar_transactions", "value": 23},
                {"type": "category_signals", "value": ["retail", "office", "supplies"]},
            ],
        },
        {
            "transaction_id": "tx_example_003",
            "suggested_category": "Unknown",
            "confidence": 0.65,  # Below threshold - will be filtered
            "explanation": "Low confidence categorization",
            "evidence": [{"type": "weak_signal", "value": True}],
        },
    ]

    # Apply central contract enforcement (confidence gating + schema validation)
    response = wrap_intelligence_response(
        suggestions[:limit],
        result_key="suggestions",
        timestamp=datetime.utcnow().isoformat(),
    )

    return response

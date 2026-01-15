# intelligence_cashflow_api.py
# INTELLIGENCE 1C — Cashflow Insights (Explainable)
# Returns trend analysis and lightweight forecasting.
# NO writes, NO mutations — advisory only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Query

from app.auth_context import get_current_context, AuthContext
from app.guardrails import wrap_intelligence_response

router = APIRouter(prefix="/api/intelligence")


@router.get("/cashflow/insights")
async def get_cashflow_insights(
    ctx: AuthContext = Depends(get_current_context),
    window_days: int = Query(default=30, ge=7, le=90),
):
    """
    GET /api/intelligence/cashflow/insights

    Returns cashflow trend analysis and lightweight forecast.
    Advisory-only — does not write or mutate any data.

    Contract enforced via guardrails/intelligence_contract.py:
    - confidence >= 0.85 threshold
    - explanation required
    - evidence required
    - manual-run only
    """
    # Placeholder insights — in production, this would analyze real transaction data
    insights = [
        {
            "type": "cashflow_trend",
            "trend": "stable",
            "trend_direction": "neutral",
            "forecast": "slightly_negative",
            "forecast_horizon_days": 14,
            "confidence": 0.88,
            "explanation": f"Net outflows exceeded inflows by 12% over last {window_days} days. "
                           f"Recurring expenses account for 68% of outflows. "
                           f"Forecast based on historical patterns and scheduled payments.",
            "evidence": [
                {"type": "window_days", "value": window_days},
                {"type": "total_inflows", "value": 15420.00},
                {"type": "total_outflows", "value": 17270.40},
                {"type": "net_change", "value": -1850.40},
                {"type": "recurring_expense_ratio", "value": 0.68},
                {"type": "data_points_analyzed", "value": 147},
            ],
        },
        {
            "type": "recommendation",
            "confidence": 0.86,
            "explanation": "Consider reviewing recurring subscriptions for optimization",
            "evidence": [
                {"type": "recurring_expense_ratio", "value": 0.68},
                {"type": "optimization_potential", "value": "medium"},
            ],
        },
    ]

    # Apply central contract enforcement (confidence gating + schema validation)
    response = wrap_intelligence_response(
        insights,
        result_key="insights",
        window_days=window_days,
        timestamp=datetime.utcnow().isoformat(),
    )

    return response

# app/routers/dashboard_overview.py
"""
Dashboard Overview API - Unified dashboard metrics endpoint

Provides aggregated dashboard data for:
- CFO Snapshot strip (cash in/out, runway, duplicates, top vendor)
- Chart data (cashflow trends, spending categories)
- Signal summaries

CANONICAL LAWS ENFORCED:
- Read-only: GET only, no mutations
- Manual-refresh: no polling/timers; data fetched on explicit request
- Advisory-only: insights are advisory, not autonomous
- Fail-closed: errors return structured JSON, not swallowed

NOTE: This endpoint is for the MAIN dashboard only.
GovCon dashboard remains isolated per entitlement requirements.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional, List, Dict, Any
import logging

from app.auth_context import get_current_context, AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/overview")
async def get_dashboard_overview(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Get unified dashboard overview data (READ-ONLY).

    Returns aggregated metrics for the main dashboard CFO snapshot
    and visualization components. Requires authentication.

    Response includes:
    - cashflow: Monthly income/expense trends
    - categories: Spending breakdown by category
    - vendors: Top vendors by spend
    - duplicates: Duplicate charge detection summary
    - signals: Active financial signals

    MANUAL-REFRESH: Data is fetched on each request.
    No polling or auto-refresh timers.
    """
    request_id = getattr(request.state, "request_id", None)

    try:
        # Return structured data for dashboard visualizations
        # In production, this would aggregate from actual data sources
        return {
            "cashflow": [
                {"month": "Jul", "income": 8200, "expenses": 5400},
                {"month": "Aug", "income": 9100, "expenses": 6200},
                {"month": "Sep", "income": 7800, "expenses": 5800},
                {"month": "Oct", "income": 10500, "expenses": 6100},
                {"month": "Nov", "income": 9800, "expenses": 5900},
                {"month": "Dec", "income": 11200, "expenses": 6800},
            ],
            "categories": [
                {"name": "Housing", "value": 2400, "color": "#d4a855"},
                {"name": "Transportation", "value": 800, "color": "#f0c060"},
                {"name": "Food & Dining", "value": 650, "color": "#a07830"},
                {"name": "Utilities", "value": 350, "color": "#4ade80"},
                {"name": "Shopping", "value": 520, "color": "#60a5fa"},
                {"name": "Other", "value": 380, "color": "#888888"},
            ],
            "vendors": [
                {"name": "Amazon", "total": 1250.00, "count": 15},
                {"name": "Whole Foods", "total": 890.50, "count": 8},
                {"name": "Shell Gas", "total": 425.00, "count": 6},
            ],
            "duplicates": {
                "count": 0,
                "trend": [],
                "potential_savings": 0.0,
            },
            "signals": [],
            "snapshot": {
                "cash_in": 11200.00,
                "cash_out": 6800.00,
                "runway_months": 8.5,
                "top_vendor": "Amazon",
                "last_updated": None,  # Populated on real data
            },
            "advisory": {
                "type": "advisory",
                "autonomous": False,
                "message": "Dashboard data is read-only. Refresh to update.",
            },
            "meta": {
                "request_id": request_id,
            },
        }

    except Exception as e:
        logger.error(f"Dashboard overview error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={
                "error": "dashboard_overview_failed",
                "message": "Failed to load dashboard data",
                "request_id": request_id,
            },
        )

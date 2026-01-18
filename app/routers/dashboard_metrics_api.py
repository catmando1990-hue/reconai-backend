from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Request

from app.auth_context import get_current_context
from app.db import get_db_connection


router = APIRouter()


def _iso(d: date) -> str:
    return d.isoformat()


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


@router.get("/dashboard/metrics")
def dashboard_metrics(request: Request) -> Dict[str, Any]:
    """
    Dashboard metrics (schema-stable).

    - Computes 30-day series from mvp_transactions for the current org.
    - Fail-closed: returns safe zeros if no data or any query issue.
    - No background computation; single request-response only.
    """
    ctx = get_current_context()
    # Get request_id from middleware-injected state (if present)
    request_id = getattr(request.state, "request_id", None)
    org_id = ctx.get("org_id") or ctx.get("org_id", None)

    today = date.today()
    days = 30
    start = today - timedelta(days=days - 1)
    labels: List[str] = [_iso(start + timedelta(days=i)) for i in range(days)]

    # Defaults (schema must remain identical)
    revenue_series = [0] * days
    expenses_series = [0] * days
    net_income_series = [0] * days

    revenue_total = 0.0
    expenses_total = 0.0

    try:
        if not org_id:
            raise ValueError("missing org_id")

        with get_db_connection() as conn:
            # Aggregate by day. tx_date is stored as text; normalize to YYYY-MM-DD.
            # amount: positive -> revenue, negative -> expense
            rows: List[Tuple[str, float]] = conn.execute(
                """
                SELECT
                  substr(tx_date, 1, 10) as d,
                  SUM(amount) as total_amount
                FROM mvp_transactions
                WHERE organization_id = ?
                  AND tx_date IS NOT NULL
                  AND substr(tx_date, 1, 10) >= ?
                  AND substr(tx_date, 1, 10) <= ?
                GROUP BY d
                """,
                (org_id, _iso(start), _iso(today)),
            ).fetchall()

        idx = {labels[i]: i for i in range(days)}
        for d, total_amount in rows:
            if d not in idx:
                continue
            i = idx[d]
            amt = _safe_float(total_amount)

            if amt >= 0:
                revenue_series[i] = int(round(amt))
                revenue_total += amt
            else:
                # store expenses as positive magnitude
                exp = abs(amt)
                expenses_series[i] = int(round(exp))
                expenses_total += exp

        # Net income per day and total
        for i in range(days):
            net_income_series[i] = int(round(revenue_series[i] - expenses_series[i]))

    except Exception:
        # Fail-closed: keep safe zeros; do not throw.
        revenue_total = 0.0
        expenses_total = 0.0

    net_income_total = revenue_total - expenses_total

    return {
        "request_id": request_id,
        "org_id": org_id,
        "period_days": days,
        "kpis": {
            "revenue": int(round(revenue_total)),
            "expenses": int(round(expenses_total)),
            "net_income": int(round(net_income_total)),
            "cash_balance": None,
        },
        "series": {
            "labels": labels,
            "revenue": revenue_series,
            "expenses": expenses_series,
            "net_income": net_income_series,
        },
        "advisory": {
            "mode": "computed",
            "message": "Computed from mvp_transactions for the selected org. Replace/extend with full ledger sources when available.",
        },
    }

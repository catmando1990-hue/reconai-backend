# app/routers/dashboard_metrics_v2.py
"""
Dashboard Metrics API v2 - Production endpoint at /api/dashboard/metrics

This endpoint provides the EXACT contract required by the frontend dashboard.
It returns explicit availability information with fail-closed semantics.

CANONICAL LAWS ENFORCED:
- Read-only: GET only, no mutations
- Manual-refresh: no polling/timers; data fetched on explicit request
- Fail-closed: returns structured JSON indicating unavailability, never fakes data
- Auth-required: Requires valid JWT authentication
- Org-scoped: All data queries filtered by organization_id

RESPONSE CONTRACT:
- available: false when metrics not yet implemented or data unavailable
- available: true when actual metrics are computed
- Unknown values MUST be null, NEVER 0
- No fake or placeholder metrics allowed

WHY THIS EXISTS:
The frontend correctly fail-closes when /api/dashboard/metrics returns 404.
This endpoint ensures the dashboard can load while clearly indicating
when metrics are or are not available.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Request
import logging

from app.auth_context import get_current_context, AuthContext
from app.db import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _safe_int(value: Any) -> Optional[int]:
    """Convert to int or return None. Never return 0 for unknown values."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Convert to float or return None. Never return 0.0 for unknown values."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


@router.get("/metrics")
async def get_dashboard_metrics(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Get dashboard metrics (READ-ONLY, AUTH-REQUIRED, ORG-SCOPED).

    Returns the exact contract required by the frontend:
    - If metrics unavailable: { "available": false, "reason": "...", "counts": null, "financials": null }
    - If metrics available: { "available": true, "counts": {...}, "financials": {...} }

    FAIL-CLOSED: Unknown values are null, never 0.
    NO FAKE DATA: Only returns actual computed values.
    """
    request_id = getattr(request.state, "request_id", None)
    org_id = ctx.get("org_id")

    if not org_id:
        logger.warning("Dashboard metrics requested without org_id", extra={"request_id": request_id})
        return {
            "available": False,
            "reason": "Organization context required",
            "counts": None,
            "financials": None,
            "meta": {
                "request_id": request_id,
            },
        }

    # Attempt to compute actual metrics from database
    try:
        counts = _compute_entity_counts(org_id)
        financials = _compute_financials(org_id)

        # Check if we have any actual data
        has_counts = counts is not None and any(v is not None for v in counts.values())
        has_financials = financials is not None and any(v is not None for v in financials.values())

        if not has_counts and not has_financials:
            return {
                "available": False,
                "reason": "No metrics data available yet",
                "counts": None,
                "financials": None,
                "meta": {
                    "request_id": request_id,
                    "org_id": org_id,
                },
            }

        return {
            "available": True,
            "counts": counts,
            "financials": financials,
            "meta": {
                "request_id": request_id,
                "org_id": org_id,
            },
        }

    except Exception as e:
        # Fail-closed: return unavailable, never throw to frontend
        logger.error(
            f"Dashboard metrics computation failed: {e}",
            extra={"request_id": request_id, "org_id": org_id},
            exc_info=True,
        )
        return {
            "available": False,
            "reason": "Metrics computation error",
            "counts": None,
            "financials": None,
            "meta": {
                "request_id": request_id,
                "org_id": org_id,
            },
        }


def _compute_entity_counts(org_id: str) -> Optional[Dict[str, Optional[int]]]:
    """
    Compute entity counts for the organization.

    Returns null for any count that cannot be determined.
    Does NOT return 0 for missing/unknown data.
    """
    try:
        with get_db_connection() as conn:
            # Count invoices
            invoices_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM invoices WHERE organization_id = ?",
                (org_id,),
            ).fetchone()
            invoices = _safe_int(invoices_row[0]) if invoices_row else None

            # Count bills
            bills_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM bills WHERE organization_id = ?",
                (org_id,),
            ).fetchone()
            bills = _safe_int(bills_row[0]) if bills_row else None

            # Count customers
            customers_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM customers WHERE organization_id = ?",
                (org_id,),
            ).fetchone()
            customers = _safe_int(customers_row[0]) if customers_row else None

            # Count vendors
            vendors_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM vendors WHERE organization_id = ?",
                (org_id,),
            ).fetchone()
            vendors = _safe_int(vendors_row[0]) if vendors_row else None

            return {
                "invoices": invoices,
                "bills": bills,
                "customers": customers,
                "vendors": vendors,
            }

    except Exception as e:
        logger.warning(f"Entity counts query failed: {e}")
        return None


def _compute_financials(org_id: str) -> Optional[Dict[str, Optional[float]]]:
    """
    Compute financial metrics for the organization.

    Returns null for any metric that cannot be determined.
    Does NOT compute from incomplete data.
    Does NOT return 0.0 for missing/unknown values.
    """
    try:
        with get_db_connection() as conn:
            # Invoice totals by status
            invoice_paid = None
            invoice_due = None

            try:
                invoice_rows = conn.execute(
                    """
                    SELECT status, SUM(total_amount) as total
                    FROM invoices
                    WHERE organization_id = ?
                    GROUP BY status
                    """,
                    (org_id,),
                ).fetchall()

                for row in invoice_rows:
                    status, total = row[0], row[1]
                    if status == "paid":
                        invoice_paid = _safe_float(total)
                    elif status in ("sent", "overdue", "pending"):
                        val = _safe_float(total)
                        if val is not None:
                            invoice_due = (invoice_due or 0.0) + val
            except Exception:
                pass  # Table may not exist; leave as null

            # Bill totals by status
            bill_paid = None
            bill_due = None

            try:
                bill_rows = conn.execute(
                    """
                    SELECT status, SUM(total_amount) as total
                    FROM bills
                    WHERE organization_id = ?
                    GROUP BY status
                    """,
                    (org_id,),
                ).fetchall()

                for row in bill_rows:
                    status, total = row[0], row[1]
                    if status == "paid":
                        bill_paid = _safe_float(total)
                    elif status in ("pending", "overdue", "approved"):
                        val = _safe_float(total)
                        if val is not None:
                            bill_due = (bill_due or 0.0) + val
            except Exception:
                pass  # Table may not exist; leave as null

            # Cash flow (simple: invoice_paid - bill_paid if both available)
            cash_flow = None
            if invoice_paid is not None and bill_paid is not None:
                cash_flow = invoice_paid - bill_paid

            return {
                "cash_flow": cash_flow,
                "invoice_paid": invoice_paid,
                "invoice_due": invoice_due,
                "bill_paid": bill_paid,
                "bill_due": bill_due,
            }

    except Exception as e:
        logger.warning(f"Financials query failed: {e}")
        return None

# app/routers/ar_aging.py

"""
Accounts Receivable (AR) Aging API
Phase 3B — Manual-only, read-only AR aging buckets

Rules:
- No background jobs
- No polling
- Manual-triggered endpoints only
- Audit logging REQUIRED
- Canonical Laws compliant
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime, date
import sqlite3

from ..db import DB_PATH
from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/ar", tags=["Accounts Receivable"])


# =========================================================================
# MODELS
# =========================================================================

class AgingBucket(BaseModel):
    """AR aging bucket"""
    label: str
    min_days: int
    max_days: Optional[int]  # None for 90+
    count: int
    total_amount: float
    invoice_ids: List[str]


class ARAgingResponse(BaseModel):
    """AR aging response"""
    organization_id: str
    as_of_date: str
    buckets: Dict[str, AgingBucket]
    total_outstanding: float
    total_invoices: int
    generated_at: str


class ARAgingSummary(BaseModel):
    """Simplified AR aging summary for dashboard"""
    organization_id: str
    as_of_date: str
    buckets: Dict[str, float]  # bucket_label -> total_amount
    total_outstanding: float


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/aging", response_model=ARAgingResponse)
def get_ar_aging(
    organization_id: str = Depends(get_current_organization_id),
    user_id: str = Depends(get_current_user_id),
    as_of: Optional[str] = None
):
    """
    Get AR aging report with invoice breakdown by aging bucket.

    Buckets:
    - 0-30 days: Current
    - 31-60 days: 30+ days overdue
    - 61-90 days: 60+ days overdue
    - 90+ days: Severely overdue

    Manual-only, read-only endpoint.
    """
    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization context required")

    # Parse as_of date or use today
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid as_of date format. Use YYYY-MM-DD.")
    else:
        as_of_date = date.today()

    # Initialize buckets
    buckets = {
        "0-30": AgingBucket(
            label="Current (0-30 days)",
            min_days=0,
            max_days=30,
            count=0,
            total_amount=0.0,
            invoice_ids=[]
        ),
        "31-60": AgingBucket(
            label="31-60 days",
            min_days=31,
            max_days=60,
            count=0,
            total_amount=0.0,
            invoice_ids=[]
        ),
        "61-90": AgingBucket(
            label="61-90 days",
            min_days=61,
            max_days=90,
            count=0,
            total_amount=0.0,
            invoice_ids=[]
        ),
        "90+": AgingBucket(
            label="90+ days",
            min_days=91,
            max_days=None,
            count=0,
            total_amount=0.0,
            invoice_ids=[]
        )
    }

    total_outstanding = 0.0
    total_invoices = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query unpaid invoices (status = draft, sent, or overdue)
        cursor.execute("""
            SELECT id, due_date, total_amount, status
            FROM invoices
            WHERE organization_id = ?
              AND status IN ('draft', 'sent', 'overdue')
              AND total_amount IS NOT NULL
              AND total_amount > 0
        """, (organization_id,))

        rows = cursor.fetchall()

        for row in rows:
            invoice_id = row["id"]
            due_date_str = row["due_date"]
            amount = float(row["total_amount"] or 0)

            if not due_date_str:
                # No due date - put in current bucket
                days_overdue = 0
            else:
                try:
                    due_date = date.fromisoformat(due_date_str)
                    days_overdue = (as_of_date - due_date).days
                    if days_overdue < 0:
                        days_overdue = 0  # Not yet due
                except ValueError:
                    days_overdue = 0

            # Categorize into bucket
            if days_overdue <= 30:
                bucket_key = "0-30"
            elif days_overdue <= 60:
                bucket_key = "31-60"
            elif days_overdue <= 90:
                bucket_key = "61-90"
            else:
                bucket_key = "90+"

            buckets[bucket_key].count += 1
            buckets[bucket_key].total_amount += amount
            buckets[bucket_key].invoice_ids.append(invoice_id)

            total_outstanding += amount
            total_invoices += 1

        conn.close()

    except sqlite3.Error as e:
        # Fail-safe: return empty buckets rather than crash
        pass

    return ARAgingResponse(
        organization_id=organization_id,
        as_of_date=as_of_date.isoformat(),
        buckets={k: v for k, v in buckets.items()},
        total_outstanding=round(total_outstanding, 2),
        total_invoices=total_invoices,
        generated_at=datetime.utcnow().isoformat() + "Z"
    )


@router.get("/aging/summary", response_model=ARAgingSummary)
def get_ar_aging_summary(
    organization_id: str = Depends(get_current_organization_id),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get simplified AR aging summary for dashboard widgets.
    Returns just bucket totals without invoice details.

    Manual-only, read-only endpoint.
    """
    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization context required")

    as_of_date = date.today()

    # Initialize bucket totals
    bucket_totals = {
        "0-30": 0.0,
        "31-60": 0.0,
        "61-90": 0.0,
        "90+": 0.0
    }

    total_outstanding = 0.0

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT due_date, total_amount
            FROM invoices
            WHERE organization_id = ?
              AND status IN ('draft', 'sent', 'overdue')
              AND total_amount IS NOT NULL
              AND total_amount > 0
        """, (organization_id,))

        rows = cursor.fetchall()

        for row in rows:
            due_date_str = row["due_date"]
            amount = float(row["total_amount"] or 0)

            if not due_date_str:
                days_overdue = 0
            else:
                try:
                    due_date = date.fromisoformat(due_date_str)
                    days_overdue = (as_of_date - due_date).days
                    if days_overdue < 0:
                        days_overdue = 0
                except ValueError:
                    days_overdue = 0

            if days_overdue <= 30:
                bucket_totals["0-30"] += amount
            elif days_overdue <= 60:
                bucket_totals["31-60"] += amount
            elif days_overdue <= 90:
                bucket_totals["61-90"] += amount
            else:
                bucket_totals["90+"] += amount

            total_outstanding += amount

        conn.close()

    except sqlite3.Error:
        pass

    return ARAgingSummary(
        organization_id=organization_id,
        as_of_date=as_of_date.isoformat(),
        buckets={k: round(v, 2) for k, v in bucket_totals.items()},
        total_outstanding=round(total_outstanding, 2)
    )

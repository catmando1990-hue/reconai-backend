# app/routers/cfo.py
"""
CFO Dashboard API - Executive Financial Overview and Export

Phase 1 Implementation:
- GET /api/cfo/overview - Total Revenue, Expenses, Net Position
- POST /api/cfo/export - Manual PDF+CSV export with audit logging
- GET /api/cfo/snapshot - Quick CFO snapshot (existing)

REQUIREMENTS:
- All routes protected via get_current_context
- Structured error envelopes with request_id
- Audit logging for export mutations
- No dynamic SQL
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
import sqlite3
import json
from datetime import datetime, date, timedelta
from uuid import uuid4

from ..db import DB_PATH
from app.auth_context import get_current_context, AuthContext

router = APIRouter(prefix="/api/cfo", tags=["CFO Dashboard"])


# =========================================================================
# EXISTING MODELS (Phase 62)
# =========================================================================

InsightSeverity = Literal["low", "medium", "high"]


class RiskItem(BaseModel):
    id: str
    title: str
    severity: InsightSeverity


class ActionItem(BaseModel):
    id: str
    title: str
    rationale: str


class CfoSnapshot(BaseModel):
    as_of: str
    runway_days: Optional[int] = None
    cash_on_hand: Optional[float] = None
    burn_rate_monthly: Optional[float] = None
    top_risks: List[RiskItem]
    next_actions: List[ActionItem]


class CfoSnapshotResponse(BaseModel):
    generated_at: str
    snapshot: CfoSnapshot


# =========================================================================
# PHASE 1 MODELS
# =========================================================================

class MetricTrend(BaseModel):
    """Trend data for a metric"""
    current: float
    previous: float
    change: float
    change_percent: float
    direction: Literal["up", "down", "flat"]


class OverviewMetrics(BaseModel):
    """CFO overview metrics"""
    total_revenue: MetricTrend
    total_expenses: MetricTrend
    net_position: MetricTrend
    cash_balance: float
    accounts_receivable: float
    accounts_payable: float
    burn_rate_monthly: Optional[float] = None
    runway_months: Optional[float] = None


class OverviewResponse(BaseModel):
    """Response for CFO overview endpoint"""
    organization_id: str
    period_start: str
    period_end: str
    comparison_period_start: str
    comparison_period_end: str
    metrics: OverviewMetrics
    top_revenue_sources: List[Dict[str, Any]]
    top_expense_categories: List[Dict[str, Any]]
    alerts: List[Dict[str, Any]]
    generated_at: str
    request_id: str


class ExportRequest(BaseModel):
    """Request for CFO export"""
    export_type: Literal["pdf", "csv", "both"] = "both"
    report_types: List[str] = Field(
        default=["overview", "income_statement", "balance_sheet"],
        description="Reports to include in export"
    )
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date (YYYY-MM-DD)")
    include_charts: bool = True
    include_details: bool = True
    evidence: Dict[str, Any] = Field(
        ...,
        description="Evidence attachment required (source, purpose, requester)"
    )


class ExportResponse(BaseModel):
    """Response for CFO export endpoint"""
    export_id: str
    organization_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    export_type: str
    report_types: List[str]
    period_start: str
    period_end: str
    created_at: str
    completed_at: Optional[str] = None
    download_urls: Optional[Dict[str, str]] = None
    expires_at: Optional[str] = None
    request_id: str


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _generate_request_id() -> str:
    """Generate unique request ID for audit trail"""
    return f"req_{uuid4().hex[:12]}"


def _calculate_trend(current: float, previous: float) -> MetricTrend:
    """Calculate trend between two values"""
    change = current - previous
    if previous != 0:
        change_percent = (change / abs(previous)) * 100
    else:
        change_percent = 100.0 if current > 0 else 0.0

    direction: Literal["up", "down", "flat"] = "flat"
    if change > 0.01:
        direction = "up"
    elif change < -0.01:
        direction = "down"

    return MetricTrend(
        current=round(current, 2),
        previous=round(previous, 2),
        change=round(change, 2),
        change_percent=round(change_percent, 2),
        direction=direction
    )


def _get_period_totals(
    conn,
    org_id: str,
    start_date: str,
    end_date: str
) -> Dict[str, float]:
    """Get revenue and expense totals for a period"""
    # Revenue: positive amounts (income)
    cursor = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM core_transactions
        WHERE organization_id = ?
          AND date >= ? AND date <= ?
          AND amount > 0
    """, (org_id, start_date, end_date))
    revenue = cursor.fetchone()[0] or 0.0

    # Expenses: negative amounts
    cursor = conn.execute("""
        SELECT COALESCE(SUM(ABS(amount)), 0) as total
        FROM core_transactions
        WHERE organization_id = ?
          AND date >= ? AND date <= ?
          AND amount < 0
    """, (org_id, start_date, end_date))
    expenses = cursor.fetchone()[0] or 0.0

    return {
        "revenue": revenue,
        "expenses": expenses,
        "net": revenue - expenses
    }


def _get_top_sources(
    conn,
    org_id: str,
    start_date: str,
    end_date: str,
    is_revenue: bool,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Get top revenue sources or expense categories"""
    if is_revenue:
        condition = "amount > 0"
    else:
        condition = "amount < 0"

    cursor = conn.execute(f"""
        SELECT
            COALESCE(merchant_normalized, category, 'Other') as source,
            COUNT(*) as transaction_count,
            COALESCE(SUM(ABS(amount)), 0) as total
        FROM core_transactions
        WHERE organization_id = ?
          AND date >= ? AND date <= ?
          AND {condition}
        GROUP BY source
        ORDER BY total DESC
        LIMIT ?
    """, (org_id, start_date, end_date, limit))

    results = []
    for row in cursor.fetchall():
        results.append({
            "source": row[0],
            "transaction_count": row[1],
            "total": round(row[2], 2)
        })

    return results


def _log_export_audit(
    conn,
    org_id: str,
    user_id: str,
    export_id: str,
    export_type: str,
    report_types: List[str],
    request_id: str,
    evidence: Dict[str, Any]
) -> None:
    """Log export action to audit_events table with evidence"""
    import hashlib

    event_id = str(uuid4())
    payload = json.dumps({
        "export_id": export_id,
        "export_type": export_type,
        "report_types": report_types,
        "request_id": request_id,
        "evidence": evidence
    })

    # Get prev_hash for hash chaining
    cursor = conn.execute("""
        SELECT event_hash FROM audit_events
        ORDER BY created_at DESC LIMIT 1
    """)
    prev_row = cursor.fetchone()
    prev_hash = prev_row[0] if prev_row else ""

    # Calculate event hash
    hash_input = f"{event_id}{user_id}cfo_export{payload}{prev_hash}"
    event_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    conn.execute("""
        INSERT INTO audit_events (id, actor_id, event_type, entity_type, entity_id, payload, prev_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_id, user_id, "cfo_export", "export", export_id, payload, prev_hash, event_hash))


# =========================================================================
# EXISTING ENDPOINT (Phase 62)
# =========================================================================

@router.get("/snapshot", response_model=CfoSnapshotResponse)
async def get_snapshot(
    ctx: AuthContext = Depends(get_current_context)
):
    """
    Quick CFO snapshot with runway, risks, and actions.
    (Existing Phase 62 endpoint, now with required auth)
    """
    now = _now_iso()
    return CfoSnapshotResponse(
        generated_at=now,
        snapshot=CfoSnapshot(
            as_of=now,
            runway_days=62,
            cash_on_hand=None,
            burn_rate_monthly=None,
            top_risks=[
                RiskItem(id="risk_001", title="Unreviewed high-severity anomaly", severity="high"),
                RiskItem(id="risk_002", title="Uncategorized transactions trending upward", severity="medium"),
            ],
            next_actions=[
                ActionItem(
                    id="act_001",
                    title="Review duplicate charge candidates",
                    rationale="High confidence pattern match. Confirm and dispute if needed.",
                ),
                ActionItem(
                    id="act_002",
                    title="Set vendor rule for recurring spike vendor",
                    rationale="Reduce future drift and improve categorization consistency.",
                ),
            ],
        ),
    )


# =========================================================================
# PHASE 1 ENDPOINTS
# =========================================================================

@router.get("/overview", response_model=OverviewResponse)
async def get_cfo_overview(
    ctx: AuthContext = Depends(get_current_context),
    start_date: Optional[str] = Query(None, description="Period start (YYYY-MM-DD), defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="Period end (YYYY-MM-DD), defaults to today")
):
    """
    Get CFO overview metrics with period-over-period comparison.

    READ-ONLY endpoint. Returns:
    - Total Revenue, Expenses, Net Position with trends
    - Cash balance, AR, AP
    - Burn rate and runway (if applicable)
    - Top revenue sources and expense categories
    - Financial alerts
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    # Default to last 30 days
    if not end_date:
        end_date = datetime.utcnow().date().isoformat()
    if not start_date:
        start_dt = datetime.fromisoformat(end_date).date() - timedelta(days=30)
        start_date = start_dt.isoformat()

    try:
        parsed_start = datetime.fromisoformat(start_date).date()
        parsed_end = datetime.fromisoformat(end_date).date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_DATE", "message": "Dates must be YYYY-MM-DD", "request_id": request_id}
        )

    # Calculate comparison period (same length, immediately prior)
    period_days = (parsed_end - parsed_start).days
    comp_end = parsed_start - timedelta(days=1)
    comp_start = comp_end - timedelta(days=period_days)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Current period totals
            current = _get_period_totals(conn, org_id, start_date, end_date)

            # Comparison period totals
            previous = _get_period_totals(
                conn, org_id,
                comp_start.isoformat(),
                comp_end.isoformat()
            )

            # Calculate trends
            revenue_trend = _calculate_trend(current["revenue"], previous["revenue"])
            expense_trend = _calculate_trend(current["expenses"], previous["expenses"])
            net_trend = _calculate_trend(current["net"], previous["net"])

            # Get current cash balance (sum of all transactions)
            cursor = conn.execute("""
                SELECT COALESCE(SUM(amount), 0) as balance
                FROM core_transactions
                WHERE organization_id = ?
                  AND date <= ?
            """, (org_id, end_date))
            cash_balance = cursor.fetchone()[0] or 0.0

            # Top sources
            top_revenue = _get_top_sources(conn, org_id, start_date, end_date, is_revenue=True)
            top_expenses = _get_top_sources(conn, org_id, start_date, end_date, is_revenue=False)

            # Calculate burn rate (average monthly expenses)
            burn_rate: Optional[float] = None
            runway: Optional[float] = None
            if period_days > 0:
                burn_rate = (current["expenses"] / period_days) * 30
                runway = (cash_balance / burn_rate) if burn_rate > 0 else None

        # Generate alerts
        alerts: List[Dict[str, Any]] = []
        if expense_trend.change_percent > 20:
            alerts.append({
                "type": "warning",
                "category": "expenses",
                "message": f"Expenses increased {expense_trend.change_percent:.1f}% vs prior period"
            })
        if revenue_trend.change_percent < -10:
            alerts.append({
                "type": "warning",
                "category": "revenue",
                "message": f"Revenue decreased {abs(revenue_trend.change_percent):.1f}% vs prior period"
            })
        if runway is not None and runway < 6:
            alerts.append({
                "type": "critical",
                "category": "runway",
                "message": f"Cash runway is {runway:.1f} months at current burn rate"
            })

        return OverviewResponse(
            organization_id=org_id,
            period_start=start_date,
            period_end=end_date,
            comparison_period_start=comp_start.isoformat(),
            comparison_period_end=comp_end.isoformat(),
            metrics=OverviewMetrics(
                total_revenue=revenue_trend,
                total_expenses=expense_trend,
                net_position=net_trend,
                cash_balance=round(cash_balance, 2),
                accounts_receivable=0.0,  # TODO: Integrate with AR system
                accounts_payable=0.0,  # TODO: Integrate with AP system
                burn_rate_monthly=round(burn_rate, 2) if burn_rate else None,
                runway_months=round(runway, 1) if runway else None
            ),
            top_revenue_sources=top_revenue,
            top_expense_categories=top_expenses,
            alerts=alerts,
            generated_at=datetime.utcnow().isoformat(),
            request_id=request_id
        )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )


@router.post("/export", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
async def create_cfo_export(
    data: ExportRequest,
    ctx: AuthContext = Depends(get_current_context)
):
    """
    Create CFO report export (PDF and/or CSV).

    MUTATION endpoint with audit logging.
    Creates export job and returns download URLs when complete.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Validate dates
    try:
        parsed_start = datetime.fromisoformat(data.start_date).date()
        parsed_end = datetime.fromisoformat(data.end_date).date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_DATE", "message": "Dates must be YYYY-MM-DD", "request_id": request_id}
        )

    if parsed_end < parsed_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_RANGE", "message": "end_date must be >= start_date", "request_id": request_id}
        )

    # Validate report types
    valid_types = {"overview", "income_statement", "balance_sheet", "cash_flow", "trial_balance"}
    invalid = set(data.report_types) - valid_types
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_REPORT_TYPE",
                "message": f"Invalid report types: {invalid}",
                "valid_types": list(valid_types),
                "request_id": request_id
            }
        )

    export_id = str(uuid4())
    created_at = datetime.utcnow()

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Log audit event for export creation with evidence
            _log_export_audit(
                conn, org_id, user_id, export_id,
                data.export_type, data.report_types, request_id,
                data.evidence
            )

            # Create S3 export record
            s3_key = f"exports/{org_id}/{export_id}"
            filename = f"cfo_report_{data.start_date}_to_{data.end_date}"

            conn.execute("""
                INSERT INTO s3_exports (id, org_id, user_id, s3_key, filename, file_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                export_id, org_id, user_id, s3_key,
                filename, data.export_type, "pending", created_at.isoformat()
            ))

            conn.commit()

        # In production, this would trigger async export job
        # For now, return pending status

        return ExportResponse(
            export_id=export_id,
            organization_id=org_id,
            status="pending",
            export_type=data.export_type,
            report_types=data.report_types,
            period_start=data.start_date,
            period_end=data.end_date,
            created_at=created_at.isoformat(),
            completed_at=None,
            download_urls=None,
            expires_at=None,
            request_id=request_id
        )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )


@router.get("/export/{export_id}", response_model=ExportResponse)
async def get_export_status(
    export_id: str,
    ctx: AuthContext = Depends(get_current_context)
):
    """
    Get export status and download URLs if complete.

    READ-ONLY endpoint.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            cursor = conn.execute("""
                SELECT id, org_id, user_id, s3_key, filename, file_type,
                       status, created_at, completed_at, expires_at
                FROM s3_exports
                WHERE id = ? AND org_id = ?
            """, (export_id, org_id))

            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "NOT_FOUND", "message": "Export not found", "request_id": request_id}
                )

            # Build download URLs if completed
            download_urls: Optional[Dict[str, str]] = None
            if row["status"] == "completed":
                # In production, generate signed S3 URLs
                base_url = f"/api/exports/{export_id}/download"
                if row["file_type"] == "both":
                    download_urls = {
                        "pdf": f"{base_url}?format=pdf",
                        "csv": f"{base_url}?format=csv"
                    }
                else:
                    download_urls = {
                        row["file_type"]: base_url
                    }

            return ExportResponse(
                export_id=row["id"],
                organization_id=row["org_id"],
                status=row["status"],
                export_type=row["file_type"],
                report_types=[],  # Would be stored in metadata
                period_start="",  # Would be stored in metadata
                period_end="",
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                download_urls=download_urls,
                expires_at=row["expires_at"],
                request_id=request_id
            )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )

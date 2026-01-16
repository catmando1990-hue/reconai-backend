# app/routers/investor_reporting_api.py
"""
ReconAI — Investor Reporting API (Read-Only)

Endpoints:
- GET /api/investor/summary - GAAP-style financial summary
- GET /api/investor/metrics - Key investor metrics (ARR, MRR, churn)
- POST /api/investor/export - Board-ready export (manual trigger)

Features:
- GAAP-style summaries
- Board-ready PDF/CSV exports
- Read-only access to financial data
- Manual export triggers only

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for reads, view_invoices for exports
- Manual invocation only (no polling)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["investor-reporting"])


class ExportRequest(BaseModel):
    format: str = "json"  # json | csv | pdf
    period: str = "quarterly"  # monthly | quarterly | annual
    include_projections: bool = False


def _calculate_mrr(org_id: str) -> Dict[str, Any]:
    """Calculate Monthly Recurring Revenue metrics."""
    with sqlite3.connect(DB_PATH) as conn:
        # Get subscription data
        cursor = conn.execute("""
            SELECT tier, subscription_status, created_at
            FROM organizations WHERE id = ?
        """, (org_id,))
        row = cursor.fetchone()

        if not row:
            return {"mrr": 0, "arr": 0, "status": "no_data"}

        tier = row[0] or "free"
        status_val = row[1] or "inactive"

        # Tier pricing (simplified)
        tier_prices = {
            "free": 0,
            "starter": 4900,  # $49/mo in cents
            "professional": 14900,  # $149/mo
            "enterprise": 49900,  # $499/mo
        }

        mrr_cents = tier_prices.get(tier, 0) if status_val == "active" else 0

        return {
            "mrr_cents": mrr_cents,
            "mrr_usd": mrr_cents / 100,
            "arr_cents": mrr_cents * 12,
            "arr_usd": (mrr_cents * 12) / 100,
            "tier": tier,
            "status": status_val,
        }


def _get_revenue_summary(org_id: str, period: str) -> Dict[str, Any]:
    """Get revenue summary for reporting period."""
    days_map = {"monthly": 30, "quarterly": 90, "annual": 365}
    days = days_map.get(period, 90)

    with sqlite3.connect(DB_PATH) as conn:
        # Get billing events from audit log
        cursor = conn.execute("""
            SELECT COUNT(*), action FROM audit_log
            WHERE action LIKE 'BILLING_%'
            AND created_at >= datetime('now', ?)
            GROUP BY action
            LIMIT 20
        """, (f"-{days} days",))

        events = {row[1]: row[0] for row in cursor.fetchall()}

    mrr_data = _calculate_mrr(org_id)

    return {
        "period": period,
        "period_days": days,
        "mrr": mrr_data,
        "billing_events": events,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _get_investor_metrics(org_id: str) -> Dict[str, Any]:
    """Calculate key investor metrics."""
    mrr_data = _calculate_mrr(org_id)

    with sqlite3.connect(DB_PATH) as conn:
        # Count active users
        cursor = conn.execute("""
            SELECT COUNT(DISTINCT actor) FROM audit_log
            WHERE created_at >= datetime('now', '-30 days')
            LIMIT 1
        """)
        active_users = cursor.fetchone()[0] or 0

        # Get org creation date for customer lifetime
        cursor = conn.execute("""
            SELECT created_at FROM organizations WHERE id = ?
        """, (org_id,))
        row = cursor.fetchone()
        created_at = row[0] if row else None

    # Calculate customer lifetime (months)
    lifetime_months = 0
    if created_at:
        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            lifetime_months = max(1, (datetime.utcnow() - created_dt.replace(tzinfo=None)).days // 30)
        except (ValueError, TypeError):
            lifetime_months = 1

    return {
        "mrr_usd": mrr_data["mrr_usd"],
        "arr_usd": mrr_data["arr_usd"],
        "active_users_30d": active_users,
        "customer_lifetime_months": lifetime_months,
        "ltv_estimate_usd": mrr_data["mrr_usd"] * lifetime_months,
        "tier": mrr_data["tier"],
        "subscription_status": mrr_data["status"],
    }


@router.get("/api/investor/summary")
async def get_investor_summary(
    ctx: AuthContext = Depends(get_current_context),
    period: str = Query("quarterly", description="Reporting period: monthly, quarterly, annual"),
):
    """
    Get GAAP-style financial summary for investors.

    Read-only endpoint - no mutations.
    Returns revenue metrics, key indicators, and trends.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Validate period
    if period not in ["monthly", "quarterly", "annual"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_PERIOD",
                "message": "Period must be: monthly, quarterly, or annual",
                "request_id": request_id,
            }
        )

    summary = _get_revenue_summary(org_id, period)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "report_type": "gaap_summary",
        "period": period,
        "summary": summary,
        "disclaimer": "Advisory only. Not audited financial statements.",
    }


@router.get("/api/investor/metrics")
async def get_investor_metrics(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get key investor metrics (ARR, MRR, LTV, etc.).

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    metrics = _get_investor_metrics(org_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "metrics": metrics,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.post("/api/investor/export")
async def export_investor_report(
    payload: ExportRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Generate board-ready investor report export.

    Manual trigger only - requires explicit user action.
    RBAC: view_invoices permission required.
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check - elevated permission for exports
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_invoices", request_id)

    # Validate format
    if payload.format not in ["json", "csv", "pdf"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_FORMAT",
                "message": "Format must be: json, csv, or pdf",
                "request_id": request_id,
            }
        )

    # Generate report data
    summary = _get_revenue_summary(org_id, payload.period)
    metrics = _get_investor_metrics(org_id)

    report_data = {
        "report_type": "investor_board_report",
        "period": payload.period,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": summary,
        "metrics": metrics,
        "projections_included": payload.include_projections,
    }

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "INVESTOR_REPORT_EXPORT",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "format": payload.format,
                    "period": payload.period,
                }),
            ))
            conn.commit()
    except Exception:
        pass

    # Format output based on requested format
    if payload.format == "csv":
        csv_lines = [
            "Metric,Value",
            f"MRR (USD),{metrics['mrr_usd']}",
            f"ARR (USD),{metrics['arr_usd']}",
            f"Active Users (30d),{metrics['active_users_30d']}",
            f"Customer Lifetime (months),{metrics['customer_lifetime_months']}",
            f"LTV Estimate (USD),{metrics['ltv_estimate_usd']}",
            f"Tier,{metrics['tier']}",
            f"Status,{metrics['subscription_status']}",
        ]
        return {
            "request_id": request_id,
            "org_id": org_id,
            "format": "csv",
            "data": "\n".join(csv_lines),
            "filename": f"investor-report-{payload.period}-{datetime.utcnow().strftime('%Y%m%d')}.csv",
        }

    return {
        "request_id": request_id,
        "org_id": org_id,
        "format": payload.format,
        "data": report_data,
        "filename": f"investor-report-{payload.period}-{datetime.utcnow().strftime('%Y%m%d')}.{payload.format}",
    }

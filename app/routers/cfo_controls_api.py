# app/routers/cfo_controls_api.py
"""
CFO / Financial Controls API (Phase 3)

GET /api/cfo/overview — Cash flow rollups + burn rate
GET /api/cfo/forecast — Projections (explicitly labeled as non-factual)
GET /api/cfo/exceptions — Financial anomalies (outliers only)

CANONICAL LAWS ENFORCED:
- Auth via get_current_context
- Org-scoped validation
- Structured error envelopes with request_id
- Immutable audit logging for forecast generation
- No auto-refresh, no background jobs
- Confidence < 0.85 must be flagged
- Projections ≠ facts (explicit labeling)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.cfo.engine import CFOEngine
from app.cfo.models import (
    CFOOverviewResponse,
    ForecastResponse,
    ExceptionsResponse,
    PeriodType,
    ExceptionSeverity,
)
from app.services.audit_store import insert_audit_event, AuditEventInput


router = APIRouter(prefix="/api/cfo", tags=["cfo-controls"])

# Engine singleton (initialized on first use)
_engine: Optional[CFOEngine] = None


def get_engine() -> CFOEngine:
    """Get or create the CFO engine."""
    global _engine
    if _engine is None:
        _engine = CFOEngine(DB_PATH)
    return _engine


@router.get("/overview", response_model=CFOOverviewResponse)
async def get_cfo_overview(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: CFOEngine = Depends(get_engine),
    lookback_months: int = Query(default=12, ge=1, le=24),
):
    """
    GET /api/cfo/overview

    Cash flow rollups (monthly + quarterly) and burn rate metrics.
    Manual-refresh only — no auto-polling.

    Query params:
    - lookback_months: Number of months to analyze (1-24, default 12)

    Returns:
    - Monthly cash flow rollups
    - Quarterly cash flow rollups
    - Burn rate metrics with runway calculation
    - KPIs summary

    CANONICAL LAWS:
    - NO auto-refresh
    - NO background jobs
    - Read-only: no mutations to source tables
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    # Validate org context
    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for CFO overview",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        # Compute rollups
        monthly_rollups = engine.compute_cash_flow_rollups(
            org_id=org_id,
            user_id=user_id,
            period_type="monthly",
            lookback_months=lookback_months,
        )

        quarterly_rollups = engine.compute_cash_flow_rollups(
            org_id=org_id,
            user_id=user_id,
            period_type="quarterly",
            lookback_months=lookback_months,
        )

        # Calculate burn rate
        burn_rate = engine.calculate_burn_rate(org_id=org_id)

        # Build KPIs
        kpis = {
            "cash_balance": float(burn_rate.current_cash_balance),
            "monthly_burn_rate": float(burn_rate.monthly_burn_rate),
            "runway_months": float(burn_rate.runway_months) if burn_rate.runway_months else None,
            "burn_trend": burn_rate.burn_trend,
            "burn_confidence": burn_rate.confidence,
            "requires_review": burn_rate.requires_review,
        }

        return CFOOverviewResponse(
            ok=True,
            request_id=request_id,
            org_id=org_id,
            generated_at=now,
            kpis=kpis,
            monthly_rollups=monthly_rollups,
            quarterly_rollups=quarterly_rollups,
            burn_rate=burn_rate,
            guardrails={
                "read_only": True,
                "auto_refresh": False,
                "manual_trigger_required": True,
                "source_table": "mvp_transactions",
                "overlay_tables": ["cfo_rollups"],
            },
            advisory={
                "mode": "computed",
                "disclaimer": "Financial data is computed from transaction history. Manual refresh required for updates.",
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "OVERVIEW_FAILED",
                "message": f"Failed to generate CFO overview: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/forecast", response_model=ForecastResponse)
async def get_forecast(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: CFOEngine = Depends(get_engine),
    horizon_days: int = Query(default=90, ge=30, le=365),
):
    """
    GET /api/cfo/forecast

    Generate cash flow forecast projections.

    IMPORTANT: ALL VALUES ARE PROJECTIONS, NOT FACTS.
    Projections are based on historical data and assumptions.
    Confidence < 0.85 is flagged for review.

    Query params:
    - horizon_days: Maximum forecast horizon (30-365, default 90)

    Returns:
    - Forecast projections at 30/60/90 day intervals
    - Confidence scores for each projection
    - Explicit disclaimer that values are projections

    CANONICAL LAWS:
    - NO auto-refresh
    - NO background jobs
    - Projections ≠ facts (explicit labeling)
    - Confidence < 0.85 flagged
    - Immutable audit logging
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    # Validate org context
    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for forecasts",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        # Generate forecast intervals based on horizon
        intervals = [30]
        if horizon_days >= 60:
            intervals.append(60)
        if horizon_days >= 90:
            intervals.append(90)
        if horizon_days >= 180:
            intervals.append(180)
        if horizon_days >= 365:
            intervals.append(365)

        # Generate forecasts
        forecast_series, audit_id = engine.generate_forecast(
            org_id=org_id,
            user_id=user_id,
            horizon_days=horizon_days,
            projection_intervals=intervals,
        )

        # Create immutable audit event
        audit_event = insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="CFO_FORECAST_GENERATED",
                entity_type="CFOForecast",
                entity_id=org_id,
                payload={
                    "request_id": request_id,
                    "org_id": org_id,
                    "horizon_days": horizon_days,
                    "projection_intervals": intervals,
                    "forecasts_count": len(forecast_series.forecasts),
                    "overall_confidence": forecast_series.overall_confidence,
                    "min_confidence": forecast_series.min_confidence,
                    "flagged_for_review": forecast_series.min_confidence < 0.85,
                },
            )
        )

        return ForecastResponse(
            ok=True,
            request_id=request_id,
            org_id=org_id,
            generated_at=now,
            forecasts=forecast_series,
            audit_event_id=audit_event.id,
            guardrails={
                "read_only": True,
                "auto_refresh": False,
                "projections_not_facts": True,
                "confidence_threshold": 0.85,
                "flagged_count": sum(
                    1 for f in forecast_series.forecasts if f.requires_review
                ),
            },
            disclaimer=(
                "ALL VALUES ARE PROJECTIONS. These forecasts are based on historical data "
                "and assumptions. Actual results may differ materially. Do not use as sole "
                "basis for financial decisions."
            ),
        )

    except Exception as e:
        # Log error in audit trail
        insert_audit_event(
            AuditEventInput(
                actor_id=user_id,
                event_type="CFO_FORECAST_ERROR",
                entity_type="CFOForecast",
                entity_id=org_id,
                payload={
                    "error": str(e),
                    "request_id": request_id,
                    "org_id": org_id,
                },
            )
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "FORECAST_FAILED",
                "message": f"Failed to generate forecast: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/exceptions", response_model=ExceptionsResponse)
async def get_exceptions(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: CFOEngine = Depends(get_engine),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: Optional[ExceptionSeverity] = Query(default=None),
    unresolved_only: bool = Query(default=True),
    detect_new: bool = Query(default=False, description="Run detection before returning results"),
):
    """
    GET /api/cfo/exceptions

    Get detected financial exceptions (outliers only).

    Query params:
    - limit: Max results (1-200, default 50)
    - offset: Pagination offset
    - severity: Filter by severity (low/medium/high/critical)
    - unresolved_only: Only return unresolved exceptions (default True)
    - detect_new: Run detection before returning (default False)

    Returns:
    - List of financial exceptions
    - Severity counts
    - Pagination info

    CANONICAL LAWS:
    - NO auto-refresh
    - Detection only, no auto-remediation
    - Read-only on source tables
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    # Validate org context
    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required for exceptions",
                "request_id": request_id,
            },
        )

    user_id = ctx.get("user_id", "unknown")
    now = datetime.utcnow().isoformat()

    try:
        # Optionally run detection
        if detect_new:
            engine.detect_exceptions(org_id=org_id, user_id=user_id)

        # Get exceptions
        exceptions, total_count = engine.get_recent_exceptions(
            org_id=org_id,
            limit=limit,
            offset=offset,
            severity=severity,
            unresolved_only=unresolved_only,
        )

        # Count by severity
        critical_count = sum(1 for e in exceptions if e.severity == "critical")
        high_count = sum(1 for e in exceptions if e.severity == "high")

        return ExceptionsResponse(
            ok=True,
            request_id=request_id,
            org_id=org_id,
            generated_at=now,
            exceptions=exceptions,
            total_count=total_count,
            critical_count=critical_count,
            high_count=high_count,
            limit=limit,
            offset=offset,
            guardrails={
                "read_only": True,
                "detection_only": True,
                "no_auto_remediation": True,
                "outlier_threshold_z": 2.5,
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "EXCEPTIONS_FAILED",
                "message": f"Failed to get exceptions: {str(e)}",
                "request_id": request_id,
            },
        )


@router.get("/stats")
async def get_cfo_stats(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    engine: CFOEngine = Depends(get_engine),
):
    """
    GET /api/cfo/stats

    Get CFO module statistics summary.
    Read-only endpoint.
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    org_id = ctx.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ORG_REQUIRED",
                "message": "Active organization required",
                "request_id": request_id,
            },
        )

    now = datetime.utcnow().isoformat()

    try:
        # Get burn rate for summary
        burn_rate = engine.calculate_burn_rate(org_id)

        # Get exception counts
        _, exception_count = engine.get_recent_exceptions(
            org_id=org_id, limit=1, unresolved_only=True
        )

        # Get recent rollups count
        monthly_rollups = engine.get_recent_rollups(org_id, "monthly", limit=12)
        quarterly_rollups = engine.get_recent_rollups(org_id, "quarterly", limit=4)

        return {
            "ok": True,
            "request_id": request_id,
            "generated_at": now,
            "stats": {
                "burn_rate": {
                    "monthly": float(burn_rate.monthly_burn_rate),
                    "runway_months": float(burn_rate.runway_months) if burn_rate.runway_months else None,
                    "trend": burn_rate.burn_trend,
                    "confidence": burn_rate.confidence,
                },
                "rollups": {
                    "monthly_periods": len(monthly_rollups),
                    "quarterly_periods": len(quarterly_rollups),
                },
                "exceptions": {
                    "unresolved_count": exception_count,
                },
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "STATS_FAILED",
                "message": f"Failed to get stats: {str(e)}",
                "request_id": request_id,
            },
        )

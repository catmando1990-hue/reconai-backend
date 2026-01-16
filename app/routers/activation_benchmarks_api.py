# app/routers/activation_benchmarks_api.py
"""
ReconAI — Activation Benchmarks & Cohorts API (STEP 17 + STEP 19 + STEP 24)

Endpoints:
- GET /api/benchmarks/activation - Activation time benchmarks
- GET /api/benchmarks/cohorts - Cohort comparison by tier/signup month
- GET /api/benchmarks/summary - Combined summary

Features:
- Benchmarks for:
  - time_to_first_bank
  - time_to_first_classification
  - time_to_first_insight
- Cohorts by:
  - tier
  - signup month
- Snapshot only (no polling, no timers)

STEP 19 Quality Controls:
- Minimum cohort size enforcement before computing benchmarks
- If below threshold: return structured "insufficient_data" state
- Applied to activation percentiles and cohort summaries

STEP 24 Kill-Switch:
- Kill-switch guard on benchmark endpoints
- FAIL CLOSED with structured error + request_id

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations
- Structured responses with request_id
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, Query

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission
from app.entitlements import guard_feature_killswitch

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


# ============================================================================
# STEP 19: Quality Controls Configuration
# ============================================================================

# Minimum sample size required before computing benchmarks
MIN_BENCHMARK_SAMPLE_SIZE = 5

# Minimum cohort size required before computing activation rates
MIN_COHORT_SIZE = 3

# Advisory message for insufficient data
INSUFFICIENT_DATA_MESSAGE = (
    "Insufficient data to compute statistically meaningful benchmarks. "
    "This protects against misleading metrics from small sample sizes."
)


def _get_activation_benchmarks() -> Dict[str, Any]:
    """
    Calculate activation benchmarks across all organizations.

    Returns aggregated statistics for time-to-first-value metrics.
    """
    benchmarks = {
        "time_to_first_bank": {
            "median_seconds": None,
            "p25_seconds": None,
            "p75_seconds": None,
            "p90_seconds": None,
            "sample_size": 0,
        },
        "time_to_first_classification": {
            "median_seconds": None,
            "p25_seconds": None,
            "p75_seconds": None,
            "p90_seconds": None,
            "sample_size": 0,
        },
        "time_to_first_insight": {
            "median_seconds": None,
            "p25_seconds": None,
            "p75_seconds": None,
            "p90_seconds": None,
            "sample_size": 0,
        },
    }

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get all organizations with created_at
            cursor = conn.execute(
                "SELECT id, created_at FROM organizations WHERE created_at IS NOT NULL"
            )
            orgs = cursor.fetchall()

            bank_times = []
            classification_times = []
            insight_times = []

            for org_id, created_at in orgs:
                try:
                    org_created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                # Check for first bank connection
                cursor = conn.execute(
                    """
                    SELECT MIN(created_at) FROM audit_log
                    WHERE metadata LIKE ? AND action IN ('PLAID_LINK_CREATED', 'BANK_CONNECTED')
                    """,
                    (f'%"org_id": "{org_id}"%',)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    try:
                        event_time = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                        bank_times.append(int((event_time - org_created).total_seconds()))
                    except (ValueError, AttributeError):
                        pass

                # Check for first classification
                cursor = conn.execute(
                    """
                    SELECT MIN(created_at) FROM audit_log
                    WHERE metadata LIKE ? AND action IN ('TRANSACTION_CLASSIFIED', 'AI_CLASSIFICATION')
                    """,
                    (f'%"org_id": "{org_id}"%',)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    try:
                        event_time = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                        classification_times.append(int((event_time - org_created).total_seconds()))
                    except (ValueError, AttributeError):
                        pass

                # Check for first insight
                cursor = conn.execute(
                    """
                    SELECT MIN(created_at) FROM audit_log
                    WHERE metadata LIKE ? AND action IN ('INSIGHT_GENERATED', 'AI_INSIGHT_CREATED')
                    """,
                    (f'%"org_id": "{org_id}"%',)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    try:
                        event_time = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                        insight_times.append(int((event_time - org_created).total_seconds()))
                    except (ValueError, AttributeError):
                        pass

            # Calculate percentiles
            if bank_times:
                bank_times.sort()
                benchmarks["time_to_first_bank"] = _calculate_percentiles(bank_times)

            if classification_times:
                classification_times.sort()
                benchmarks["time_to_first_classification"] = _calculate_percentiles(classification_times)

            if insight_times:
                insight_times.sort()
                benchmarks["time_to_first_insight"] = _calculate_percentiles(insight_times)

    except Exception:
        pass

    return benchmarks


def _calculate_percentiles(sorted_values: List[int]) -> Dict[str, Any]:
    """
    Calculate percentile statistics from sorted list.

    STEP 19: Enforces minimum sample size before computing percentiles.
    Returns insufficient_data state if below threshold.
    """
    n = len(sorted_values)

    # STEP 19: Check minimum sample size
    if n < MIN_BENCHMARK_SAMPLE_SIZE:
        return {
            "median_seconds": None,
            "p25_seconds": None,
            "p75_seconds": None,
            "p90_seconds": None,
            "sample_size": n,
            "insufficient_data": True,
            "min_required": MIN_BENCHMARK_SAMPLE_SIZE,
            "message": INSUFFICIENT_DATA_MESSAGE,
        }

    def percentile(p: float) -> int:
        idx = int(p * (n - 1))
        return sorted_values[idx]

    return {
        "median_seconds": percentile(0.5),
        "p25_seconds": percentile(0.25),
        "p75_seconds": percentile(0.75),
        "p90_seconds": percentile(0.90),
        "sample_size": n,
        "insufficient_data": False,
    }


def _format_duration(seconds: Optional[int]) -> Optional[str]:
    """Format duration in human-readable format."""
    if seconds is None:
        return None

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"
    else:
        days = seconds // 86400
        return f"{days}d"


def _get_cohort_by_tier() -> List[Dict[str, Any]]:
    """
    Get activation cohorts grouped by tier.

    STEP 19: Enforces minimum cohort size before computing activation rates.
    """
    cohorts = []
    tiers = ["free", "starter", "professional", "enterprise"]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            for tier in tiers:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM organizations WHERE tier = ?",
                    (tier,)
                )
                total = cursor.fetchone()[0]

                # Count activated (has any activation event)
                cursor = conn.execute(
                    """
                    SELECT COUNT(DISTINCT o.id) FROM organizations o
                    JOIN audit_log a ON a.metadata LIKE '%"org_id": "' || o.id || '"%'
                    WHERE o.tier = ? AND a.action IN ('PLAID_LINK_CREATED', 'TRANSACTION_CLASSIFIED', 'INSIGHT_GENERATED')
                    """,
                    (tier,)
                )
                activated = cursor.fetchone()[0]

                # STEP 19: Check minimum cohort size
                if total < MIN_COHORT_SIZE:
                    cohorts.append({
                        "cohort_type": "tier",
                        "cohort_value": tier,
                        "total_orgs": total,
                        "activated_orgs": None,
                        "activation_rate": None,
                        "insufficient_data": True,
                        "min_required": MIN_COHORT_SIZE,
                        "message": INSUFFICIENT_DATA_MESSAGE,
                    })
                else:
                    cohorts.append({
                        "cohort_type": "tier",
                        "cohort_value": tier,
                        "total_orgs": total,
                        "activated_orgs": activated,
                        "activation_rate": round((activated / total * 100), 1) if total > 0 else 0,
                        "insufficient_data": False,
                    })

    except Exception:
        # Return default cohorts on error
        for tier in tiers:
            cohorts.append({
                "cohort_type": "tier",
                "cohort_value": tier,
                "total_orgs": 0,
                "activated_orgs": None,
                "activation_rate": None,
                "insufficient_data": True,
                "min_required": MIN_COHORT_SIZE,
                "message": INSUFFICIENT_DATA_MESSAGE,
            })

    return cohorts


def _get_cohort_by_signup_month() -> List[Dict[str, Any]]:
    """
    Get activation cohorts grouped by signup month.

    STEP 19: Enforces minimum cohort size before computing activation rates.
    """
    cohorts = []

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get last 6 months
            now = datetime.utcnow()
            for i in range(6):
                month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1)

                month_key = month_start.strftime("%Y-%m")

                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM organizations
                    WHERE created_at >= ? AND created_at < ?
                    """,
                    (month_start.isoformat(), month_end.isoformat())
                )
                total = cursor.fetchone()[0]

                # Count activated in this cohort
                cursor = conn.execute(
                    """
                    SELECT COUNT(DISTINCT o.id) FROM organizations o
                    JOIN audit_log a ON a.metadata LIKE '%"org_id": "' || o.id || '"%'
                    WHERE o.created_at >= ? AND o.created_at < ?
                    AND a.action IN ('PLAID_LINK_CREATED', 'TRANSACTION_CLASSIFIED', 'INSIGHT_GENERATED')
                    """,
                    (month_start.isoformat(), month_end.isoformat())
                )
                activated = cursor.fetchone()[0]

                # STEP 19: Check minimum cohort size
                if total < MIN_COHORT_SIZE:
                    cohorts.append({
                        "cohort_type": "signup_month",
                        "cohort_value": month_key,
                        "total_orgs": total,
                        "activated_orgs": None,
                        "activation_rate": None,
                        "insufficient_data": True,
                        "min_required": MIN_COHORT_SIZE,
                        "message": INSUFFICIENT_DATA_MESSAGE,
                    })
                else:
                    cohorts.append({
                        "cohort_type": "signup_month",
                        "cohort_value": month_key,
                        "total_orgs": total,
                        "activated_orgs": activated,
                        "activation_rate": round((activated / total * 100), 1) if total > 0 else 0,
                        "insufficient_data": False,
                    })

    except Exception:
        pass

    return cohorts


@router.get("/activation")
async def get_activation_benchmarks(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/benchmarks/activation

    Get activation time benchmarks across all organizations.

    STEP 19: Returns insufficient_data state if below minimum sample size.
    STEP 24: Guarded by benchmarks kill-switch.

    Read-only endpoint - snapshot only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("benchmarks", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    benchmarks = _get_activation_benchmarks()

    # Format durations for display
    formatted = {}
    has_insufficient_data = False
    for metric, data in benchmarks.items():
        if data.get("insufficient_data"):
            has_insufficient_data = True
        formatted[metric] = {
            **data,
            "median_formatted": _format_duration(data.get("median_seconds")),
            "p25_formatted": _format_duration(data.get("p25_seconds")),
            "p75_formatted": _format_duration(data.get("p75_seconds")),
            "p90_formatted": _format_duration(data.get("p90_seconds")),
        }

    return {
        "request_id": request_id,
        "benchmarks": formatted,
        "snapshot_at": datetime.utcnow().isoformat(),
        "advisory": "Benchmarks are calculated from anonymized aggregate data. Individual org data is not exposed.",
        "quality_controls": {
            "min_sample_size": MIN_BENCHMARK_SAMPLE_SIZE,
            "has_insufficient_data": has_insufficient_data,
        },
    }


@router.get("/cohorts")
async def get_cohorts(
    ctx: AuthContext = Depends(get_current_context),
    cohort_type: Optional[str] = Query(None, description="Filter by cohort type: tier, signup_month"),
):
    """
    GET /api/benchmarks/cohorts

    Get activation cohorts by tier and signup month.

    STEP 19: Returns insufficient_data state for cohorts below minimum size.
    STEP 24: Guarded by benchmarks kill-switch.

    Read-only endpoint - snapshot only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("benchmarks", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Get cohorts based on filter
    cohorts = []

    if cohort_type is None or cohort_type == "tier":
        cohorts.extend(_get_cohort_by_tier())

    if cohort_type is None or cohort_type == "signup_month":
        cohorts.extend(_get_cohort_by_signup_month())

    # STEP 19: Check for insufficient data
    insufficient_count = sum(1 for c in cohorts if c.get("insufficient_data"))

    return {
        "request_id": request_id,
        "cohorts": cohorts,
        "cohort_types": ["tier", "signup_month"],
        "snapshot_at": datetime.utcnow().isoformat(),
        "advisory": "Cohort data is calculated from anonymized aggregate data.",
        "quality_controls": {
            "min_cohort_size": MIN_COHORT_SIZE,
            "insufficient_data_count": insufficient_count,
            "total_cohorts": len(cohorts),
        },
    }


@router.get("/summary")
async def get_benchmark_summary(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/benchmarks/summary

    Get combined benchmark summary with activation benchmarks and cohorts.

    STEP 19: Includes quality control metadata and insufficient_data states.
    STEP 24: Guarded by benchmarks kill-switch.

    Read-only endpoint - snapshot only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("benchmarks", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    benchmarks = _get_activation_benchmarks()
    tier_cohorts = _get_cohort_by_tier()
    month_cohorts = _get_cohort_by_signup_month()

    # STEP 19: Calculate overall activation rate only from cohorts with sufficient data
    valid_cohorts = [c for c in tier_cohorts if not c.get("insufficient_data")]
    total_orgs = sum(c["total_orgs"] for c in valid_cohorts)
    activated_orgs = sum(c.get("activated_orgs", 0) or 0 for c in valid_cohorts)

    # STEP 19: Check if we have enough data for overall rate
    if total_orgs < MIN_COHORT_SIZE:
        overall_activation_rate = None
        summary_insufficient_data = True
    else:
        overall_activation_rate = round((activated_orgs / total_orgs * 100), 1) if total_orgs > 0 else 0
        summary_insufficient_data = False

    # STEP 19: Count insufficient data across all sources
    benchmark_insufficient = sum(1 for _, d in benchmarks.items() if d.get("insufficient_data"))
    cohort_insufficient = sum(1 for c in tier_cohorts + month_cohorts if c.get("insufficient_data"))

    return {
        "request_id": request_id,
        "summary": {
            "total_organizations": total_orgs,
            "activated_organizations": activated_orgs,
            "overall_activation_rate": overall_activation_rate,
            "insufficient_data": summary_insufficient_data,
        },
        "benchmarks": {
            metric: {
                "median_formatted": _format_duration(data.get("median_seconds")),
                "sample_size": data.get("sample_size", 0),
                "insufficient_data": data.get("insufficient_data", False),
            }
            for metric, data in benchmarks.items()
        },
        "cohorts_by_tier": tier_cohorts,
        "cohorts_by_month": month_cohorts[:3],  # Last 3 months
        "snapshot_at": datetime.utcnow().isoformat(),
        "quality_controls": {
            "min_benchmark_sample_size": MIN_BENCHMARK_SAMPLE_SIZE,
            "min_cohort_size": MIN_COHORT_SIZE,
            "benchmarks_with_insufficient_data": benchmark_insufficient,
            "cohorts_with_insufficient_data": cohort_insufficient,
        },
    }

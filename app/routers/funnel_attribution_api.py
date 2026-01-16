# app/routers/funnel_attribution_api.py
"""
ReconAI — Activation → Revenue Funnel Attribution API (STEP 23)

Endpoints:
- GET /api/funnel/attribution - Full funnel attribution metrics
- GET /api/funnel/stages - Funnel stage breakdown
- GET /api/funnel/conversion - Conversion rates by stage
- GET /api/funnel/revenue - Revenue attribution by stage

Features:
- Read-only funnel attribution metrics
- Activation → Revenue funnel stages
- Conversion rates between stages
- Revenue attribution by activation milestone
- Manual generation only
- Structured responses with request_id

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations
- Structured responses with request_id
- Dashboard-only
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(prefix="/api/funnel", tags=["funnel-attribution"])


# Funnel stages definition
FUNNEL_STAGES = [
    {
        "id": "signup",
        "name": "Sign Up",
        "description": "User creates account",
        "order": 1,
    },
    {
        "id": "bank_connected",
        "name": "Bank Connected",
        "description": "First Plaid link created",
        "order": 2,
    },
    {
        "id": "first_classification",
        "name": "First Classification",
        "description": "First transaction classified",
        "order": 3,
    },
    {
        "id": "first_insight",
        "name": "First Insight",
        "description": "First AI insight generated",
        "order": 4,
    },
    {
        "id": "activated",
        "name": "Activated",
        "description": "All activation milestones completed",
        "order": 5,
    },
    {
        "id": "upgrade_started",
        "name": "Upgrade Started",
        "description": "User initiated upgrade flow",
        "order": 6,
    },
    {
        "id": "converted",
        "name": "Converted",
        "description": "Paid subscription started",
        "order": 7,
    },
]


def _get_org_metrics(org_id: str) -> Dict[str, Any]:
    """Get organization funnel metrics from DB."""
    metrics = {
        "signup_at": None,
        "bank_connected_at": None,
        "first_classification_at": None,
        "first_insight_at": None,
        "activated_at": None,
        "upgrade_started_at": None,
        "converted_at": None,
        "current_tier": "free",
        "revenue_total": 0.0,
    }

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get org creation time
            cursor = conn.execute(
                "SELECT created_at, tier FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if row:
                metrics["signup_at"] = row[0]
                metrics["current_tier"] = row[1] or "free"

            # Check audit log for activation events
            event_map = {
                "PLAID_LINK_CREATED": "bank_connected_at",
                "TRANSACTION_CLASSIFIED": "first_classification_at",
                "INSIGHT_GENERATED": "first_insight_at",
                "UPGRADE_STARTED": "upgrade_started_at",
                "SUBSCRIPTION_CREATED": "converted_at",
            }

            for event, field in event_map.items():
                cursor = conn.execute(
                    """SELECT MIN(timestamp) FROM audit_log
                       WHERE action = ? AND metadata LIKE ?""",
                    (event, f'%"org_id": "{org_id}"%')
                )
                row = cursor.fetchone()
                if row and row[0]:
                    metrics[field] = row[0]

            # Check if fully activated
            if all([
                metrics["bank_connected_at"],
                metrics["first_classification_at"],
                metrics["first_insight_at"],
            ]):
                # Set activated_at to the latest of the three
                times = [
                    metrics["bank_connected_at"],
                    metrics["first_classification_at"],
                    metrics["first_insight_at"],
                ]
                metrics["activated_at"] = max(t for t in times if t)

    except Exception:
        pass

    return metrics


def _calculate_stage_times(metrics: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Calculate time spent at each stage transition (in seconds)."""
    times = {}

    def _parse_time(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    signup = _parse_time(metrics.get("signup_at"))
    bank = _parse_time(metrics.get("bank_connected_at"))
    classification = _parse_time(metrics.get("first_classification_at"))
    insight = _parse_time(metrics.get("first_insight_at"))
    activated = _parse_time(metrics.get("activated_at"))
    upgrade = _parse_time(metrics.get("upgrade_started_at"))
    converted = _parse_time(metrics.get("converted_at"))

    if signup and bank:
        times["signup_to_bank"] = (bank - signup).total_seconds()
    if bank and classification:
        times["bank_to_classification"] = (classification - bank).total_seconds()
    if classification and insight:
        times["classification_to_insight"] = (insight - classification).total_seconds()
    if insight and activated:
        times["insight_to_activated"] = (activated - insight).total_seconds()
    if activated and upgrade:
        times["activated_to_upgrade"] = (upgrade - activated).total_seconds()
    if upgrade and converted:
        times["upgrade_to_converted"] = (converted - upgrade).total_seconds()
    if signup and converted:
        times["total_time_to_revenue"] = (converted - signup).total_seconds()

    return times


def _format_duration(seconds: Optional[float]) -> Optional[str]:
    """Format duration in human-readable format."""
    if seconds is None:
        return None

    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        return f"{days}d {hours}h"


@router.get("/attribution")
async def funnel_attribution(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/funnel/attribution

    Get full funnel attribution metrics for the organization.

    Shows progression through activation stages to revenue,
    with timestamps and duration at each stage.

    Read-only endpoint - manual refresh only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    metrics = _get_org_metrics(org_id)
    stage_times = _calculate_stage_times(metrics)

    # Build attribution data
    stages_completed = []
    stages_pending = []

    stage_field_map = {
        "signup": "signup_at",
        "bank_connected": "bank_connected_at",
        "first_classification": "first_classification_at",
        "first_insight": "first_insight_at",
        "activated": "activated_at",
        "upgrade_started": "upgrade_started_at",
        "converted": "converted_at",
    }

    for stage in FUNNEL_STAGES:
        field = stage_field_map.get(stage["id"])
        timestamp = metrics.get(field) if field else None

        stage_data = {
            "id": stage["id"],
            "name": stage["name"],
            "description": stage["description"],
            "order": stage["order"],
            "timestamp": timestamp,
            "completed": timestamp is not None,
        }

        if timestamp:
            stages_completed.append(stage_data)
        else:
            stages_pending.append(stage_data)

    # Calculate overall progress
    total_stages = len(FUNNEL_STAGES)
    completed_stages = len(stages_completed)
    progress_percent = round((completed_stages / total_stages) * 100, 1)

    return {
        "request_id": request_id,
        "attribution": {
            "org_id": org_id,
            "current_tier": metrics["current_tier"],
            "progress": {
                "completed": completed_stages,
                "total": total_stages,
                "percent": progress_percent,
            },
            "stages_completed": stages_completed,
            "stages_pending": stages_pending,
            "timing": {
                "raw_seconds": stage_times,
                "formatted": {
                    k: _format_duration(v) for k, v in stage_times.items()
                },
            },
            "revenue_attributed": metrics["revenue_total"],
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stages")
async def funnel_stages(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/funnel/stages

    Get funnel stage definitions and current status.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    metrics = _get_org_metrics(org_id)

    stage_field_map = {
        "signup": "signup_at",
        "bank_connected": "bank_connected_at",
        "first_classification": "first_classification_at",
        "first_insight": "first_insight_at",
        "activated": "activated_at",
        "upgrade_started": "upgrade_started_at",
        "converted": "converted_at",
    }

    stages = []
    for stage in FUNNEL_STAGES:
        field = stage_field_map.get(stage["id"])
        timestamp = metrics.get(field) if field else None

        stages.append({
            **stage,
            "timestamp": timestamp,
            "completed": timestamp is not None,
        })

    return {
        "request_id": request_id,
        "stages": stages,
        "total_stages": len(FUNNEL_STAGES),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/conversion")
async def conversion_rates(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/funnel/conversion

    Get conversion rates between funnel stages.

    Note: For single-org view, shows binary completion.
    Platform-wide conversion rates require admin access.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    metrics = _get_org_metrics(org_id)

    # For single org, conversion is binary (0 or 100%)
    conversions = []

    stage_pairs = [
        ("signup", "bank_connected", "signup_at", "bank_connected_at"),
        ("bank_connected", "first_classification", "bank_connected_at", "first_classification_at"),
        ("first_classification", "first_insight", "first_classification_at", "first_insight_at"),
        ("first_insight", "activated", "first_insight_at", "activated_at"),
        ("activated", "upgrade_started", "activated_at", "upgrade_started_at"),
        ("upgrade_started", "converted", "upgrade_started_at", "converted_at"),
    ]

    for from_stage, to_stage, from_field, to_field in stage_pairs:
        from_completed = metrics.get(from_field) is not None
        to_completed = metrics.get(to_field) is not None

        if from_completed:
            rate = 100.0 if to_completed else 0.0
        else:
            rate = None  # Can't calculate if from_stage not completed

        conversions.append({
            "from_stage": from_stage,
            "to_stage": to_stage,
            "from_completed": from_completed,
            "to_completed": to_completed,
            "conversion_rate": rate,
        })

    # Overall funnel conversion
    overall = {
        "signup_to_activated": 100.0 if metrics.get("activated_at") else 0.0,
        "signup_to_converted": 100.0 if metrics.get("converted_at") else 0.0,
        "activated_to_converted": (
            100.0 if metrics.get("converted_at") else 0.0
        ) if metrics.get("activated_at") else None,
    }

    return {
        "request_id": request_id,
        "conversions": {
            "by_stage": conversions,
            "overall": overall,
        },
        "note": "Single-org view shows binary completion. Platform metrics available to admins.",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/revenue")
async def revenue_attribution(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/funnel/revenue

    Get revenue attribution by activation milestone.

    Shows which activation milestones contributed to conversion.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    metrics = _get_org_metrics(org_id)
    stage_times = _calculate_stage_times(metrics)

    # Revenue is only attributed if converted
    is_converted = metrics.get("converted_at") is not None
    current_tier = metrics.get("current_tier", "free")

    # Tier pricing (simplified - production would use actual pricing data)
    tier_mrr = {
        "free": 0,
        "starter": 29,
        "professional": 99,
        "enterprise": 299,
    }

    mrr = tier_mrr.get(current_tier, 0)

    # Attribution by milestone (if converted)
    attribution = []
    if is_converted:
        # Attribution model: equal weight to each completed milestone before conversion
        milestones = [
            ("bank_connected", "Bank Connection"),
            ("first_classification", "First Classification"),
            ("first_insight", "First Insight"),
            ("activated", "Full Activation"),
        ]

        completed_milestones = [
            m for m in milestones
            if metrics.get(f"{m[0]}_at") is not None
        ]

        if completed_milestones:
            weight_per_milestone = mrr / len(completed_milestones)
            for milestone_id, milestone_name in completed_milestones:
                attribution.append({
                    "milestone": milestone_id,
                    "name": milestone_name,
                    "attributed_mrr": round(weight_per_milestone, 2),
                    "weight_percent": round(100 / len(completed_milestones), 1),
                })

    # Time to revenue
    ttr = stage_times.get("total_time_to_revenue")

    return {
        "request_id": request_id,
        "revenue": {
            "org_id": org_id,
            "current_tier": current_tier,
            "is_converted": is_converted,
            "mrr": mrr,
            "arr": mrr * 12,
            "attribution": attribution,
            "time_to_revenue": {
                "seconds": ttr,
                "formatted": _format_duration(ttr),
            },
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

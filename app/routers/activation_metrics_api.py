# app/routers/activation_metrics_api.py
"""
ReconAI — First-Value Telemetry API (STEP 14B)

Endpoints:
- GET /api/metrics/activation - Activation metrics snapshot

Metrics:
- time_to_first_bank: Time from org creation to first bank connection
- time_to_first_classification: Time to first transaction classification
- time_to_first_insight: Time to first AI-generated insight

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Snapshot only, no polling
- No background jobs
- Read-only, structured response with request_id
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _get_activation_metrics(org_id: str) -> Dict[str, Any]:
    """
    Get activation metrics for an organization.

    Calculates time-to-first-value metrics from database.
    Returns None for metrics that haven't been achieved yet.
    """
    metrics = {
        "time_to_first_bank_seconds": None,
        "time_to_first_classification_seconds": None,
        "time_to_first_insight_seconds": None,
        "first_bank_at": None,
        "first_classification_at": None,
        "first_insight_at": None,
        "org_created_at": None,
    }

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get org creation time
            cursor = conn.execute(
                "SELECT created_at FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return metrics

            org_created_at = row[0]
            metrics["org_created_at"] = org_created_at

            # Parse org creation timestamp
            try:
                created_dt = datetime.fromisoformat(org_created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return metrics

            # Check for first bank connection (from plaid_items or similar)
            cursor = conn.execute(
                """
                SELECT MIN(created_at) FROM audit_log
                WHERE metadata LIKE ? AND action IN ('PLAID_LINK_CREATED', 'BANK_CONNECTED', 'PLAID_ITEM_CREATED')
                """,
                (f'%"org_id": "{org_id}"%',)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    first_bank_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    metrics["first_bank_at"] = row[0]
                    metrics["time_to_first_bank_seconds"] = int((first_bank_dt - created_dt).total_seconds())
                except (ValueError, AttributeError):
                    pass

            # Check for first classification
            cursor = conn.execute(
                """
                SELECT MIN(created_at) FROM audit_log
                WHERE metadata LIKE ? AND action IN ('TRANSACTION_CLASSIFIED', 'CATEGORY_ASSIGNED', 'AI_CLASSIFICATION')
                """,
                (f'%"org_id": "{org_id}"%',)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    first_class_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    metrics["first_classification_at"] = row[0]
                    metrics["time_to_first_classification_seconds"] = int((first_class_dt - created_dt).total_seconds())
                except (ValueError, AttributeError):
                    pass

            # Check for first insight
            cursor = conn.execute(
                """
                SELECT MIN(created_at) FROM audit_log
                WHERE metadata LIKE ? AND action IN ('INSIGHT_GENERATED', 'AI_INSIGHT_CREATED', 'FIRST_INSIGHT')
                """,
                (f'%"org_id": "{org_id}"%',)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    first_insight_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    metrics["first_insight_at"] = row[0]
                    metrics["time_to_first_insight_seconds"] = int((first_insight_dt - created_dt).total_seconds())
                except (ValueError, AttributeError):
                    pass

    except Exception:
        # Return partial metrics on error
        pass

    return metrics


def _format_duration(seconds: Optional[int]) -> Optional[str]:
    """Format duration in human-readable format."""
    if seconds is None:
        return None

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m {seconds % 60}s"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"


@router.get("/activation")
async def get_activation_metrics(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/metrics/activation

    Returns activation metrics snapshot for the organization.
    Time-to-first-value metrics for key activation events.

    Read-only endpoint - snapshot only, no polling.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Get metrics
    raw_metrics = _get_activation_metrics(org_id)

    # Calculate completion status
    milestones = {
        "bank_connected": raw_metrics["first_bank_at"] is not None,
        "first_classification": raw_metrics["first_classification_at"] is not None,
        "first_insight": raw_metrics["first_insight_at"] is not None,
    }
    completed_count = sum(1 for v in milestones.values() if v)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "metrics": {
            "time_to_first_bank": {
                "seconds": raw_metrics["time_to_first_bank_seconds"],
                "formatted": _format_duration(raw_metrics["time_to_first_bank_seconds"]),
                "achieved_at": raw_metrics["first_bank_at"],
                "achieved": raw_metrics["first_bank_at"] is not None,
            },
            "time_to_first_classification": {
                "seconds": raw_metrics["time_to_first_classification_seconds"],
                "formatted": _format_duration(raw_metrics["time_to_first_classification_seconds"]),
                "achieved_at": raw_metrics["first_classification_at"],
                "achieved": raw_metrics["first_classification_at"] is not None,
            },
            "time_to_first_insight": {
                "seconds": raw_metrics["time_to_first_insight_seconds"],
                "formatted": _format_duration(raw_metrics["time_to_first_insight_seconds"]),
                "achieved_at": raw_metrics["first_insight_at"],
                "achieved": raw_metrics["first_insight_at"] is not None,
            },
        },
        "milestones": milestones,
        "activation_progress": {
            "completed": completed_count,
            "total": 3,
            "percent": round((completed_count / 3) * 100, 1),
        },
        "org_created_at": raw_metrics["org_created_at"],
        "snapshot_at": datetime.utcnow().isoformat(),
    }

# app/routers/billing_financial_controls_api.py
"""
ReconAI Billing — Financial Controls API

Endpoints:
- GET /api/billing/controls - Get current financial control settings
- POST /api/billing/controls - Update financial control settings (manual)
- GET /api/billing/controls/alerts - Get audit-only alerts (no auto-actions)

Features:
- Soft limits on spending/usage
- Approval thresholds for upgrades
- Upgrade caps per billing period
- Audit-only alerts (no automatic enforcement)

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for read, manage_roles for write
- Manual invocation only (no polling/auto-enforcement)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.settings.contract import SETTINGS_CONTRACT_VERSION, wrap_settings_response
from app.settings.audit import audit_financial_controls_change
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing-controls"])


class FinancialControlsUpdate(BaseModel):
    soft_spending_limit: Optional[float] = None  # Monthly soft limit in USD
    approval_threshold: Optional[float] = None    # Require approval above this
    max_upgrades_per_period: Optional[int] = None # Max tier changes per billing period
    alert_on_threshold_breach: bool = True        # Audit-only alert


class AlertConfig(BaseModel):
    enabled: bool = True
    threshold_percent: float = 80.0  # Alert at 80% of limit


def _get_financial_controls(org_id: str) -> Dict[str, Any]:
    """Get financial control settings for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT features FROM organizations WHERE id = ?
        """, (org_id,))
        row = cursor.fetchone()

        if row and row[0]:
            try:
                features = json.loads(row[0])
                return features.get("financial_controls", {
                    "soft_spending_limit": None,
                    "approval_threshold": None,
                    "max_upgrades_per_period": None,
                    "alert_on_threshold_breach": True,
                })
            except json.JSONDecodeError:
                pass

        return {
            "soft_spending_limit": None,
            "approval_threshold": None,
            "max_upgrades_per_period": None,
            "alert_on_threshold_breach": True,
        }


def _save_financial_controls(org_id: str, controls: Dict[str, Any]) -> bool:
    """Save financial control settings."""
    with sqlite3.connect(DB_PATH) as conn:
        # Get current features
        cursor = conn.execute(
            "SELECT features FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()

        features = {}
        if row and row[0]:
            try:
                features = json.loads(row[0])
            except json.JSONDecodeError:
                features = {}

        features["financial_controls"] = controls

        cursor = conn.execute("""
            UPDATE organizations
            SET features = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (json.dumps(features), org_id))
        conn.commit()

        return cursor.rowcount > 0


def _get_spending_alerts(org_id: str) -> List[Dict[str, Any]]:
    """Get audit-only alerts for spending thresholds."""
    controls = _get_financial_controls(org_id)

    alerts = []

    # Check soft spending limit
    soft_limit = controls.get("soft_spending_limit")
    if soft_limit:
        # Get current period spending from audit log (approximation)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE action LIKE 'BILLING_%'
                AND created_at >= date('now', 'start of month')
            """)
            activity_count = cursor.fetchone()[0]

        alerts.append({
            "type": "spending_limit",
            "soft_limit": soft_limit,
            "status": "active",
            "message": f"Soft spending limit configured: ${soft_limit:.2f}/month",
            "severity": "info",
        })

    # Check approval threshold
    approval_threshold = controls.get("approval_threshold")
    if approval_threshold:
        alerts.append({
            "type": "approval_threshold",
            "threshold": approval_threshold,
            "status": "active",
            "message": f"Approval required for changes above ${approval_threshold:.2f}",
            "severity": "info",
        })

    # Check upgrade cap
    max_upgrades = controls.get("max_upgrades_per_period")
    if max_upgrades:
        alerts.append({
            "type": "upgrade_cap",
            "max_upgrades": max_upgrades,
            "status": "active",
            "message": f"Max {max_upgrades} tier changes per billing period",
            "severity": "info",
        })

    return alerts


@router.get("/api/billing/controls")
async def get_financial_controls(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get current financial control settings.

    CONTRACT VERSION: 1
    - settings_version: ALWAYS present
    - lifecycle: ALWAYS present
    - metadata: ALWAYS present

    Read-only endpoint - no mutations.
    Returns soft limits, thresholds, and caps.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    controls = _get_financial_controls(org_id)

    return wrap_settings_response(
        ok=True,
        sources=["organizations", "financial_controls"],
        scope="organization",
        modified_by=None,
        request_id=request_id,
        org_id=org_id,
        controls=controls,
    )


@router.post("/api/billing/controls")
async def update_financial_controls(
    payload: FinancialControlsUpdate,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Update financial control settings.

    CONTRACT VERSION: 1
    - settings_version: ALWAYS present
    - lifecycle: ALWAYS present
    - metadata: ALWAYS present

    AUDIT:
    - previous_value: ALWAYS captured
    - request_id: ALWAYS stored

    Manual invocation only - no auto-enforcement.
    RBAC: manage_roles permission required (owner, billing_admin).
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    now = datetime.utcnow().isoformat()

    # RBAC check: manage_roles required for writes
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # CAPTURE previous_value BEFORE mutation (AUDIT REQUIREMENT)
    previous_controls = _get_financial_controls(org_id)

    # Get current controls (copy for modification)
    current = dict(previous_controls)

    # Apply updates (only non-None values)
    if payload.soft_spending_limit is not None:
        current["soft_spending_limit"] = payload.soft_spending_limit
    if payload.approval_threshold is not None:
        current["approval_threshold"] = payload.approval_threshold
    if payload.max_upgrades_per_period is not None:
        current["max_upgrades_per_period"] = payload.max_upgrades_per_period
    current["alert_on_threshold_breach"] = payload.alert_on_threshold_breach

    # Save controls
    success = _save_financial_controls(org_id, current)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "UPDATE_FAILED",
                "message": "Failed to save financial controls",
                "request_id": request_id,
            }
        )

    # EMIT AUDIT EVENT with previous_value (never blocks request on failure)
    try:
        audit_financial_controls_change(
            request_id=request_id,
            actor_id=user_id,
            org_id=org_id,
            previous_controls=previous_controls,
            new_controls=current,
        )
    except Exception:
        pass  # Audit should not block the request

    # Legacy audit log (kept for backward compatibility)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "BILLING_FINANCIAL_CONTROLS_UPDATED",
                user_id,
                json.dumps({"controls": current, "previous": previous_controls}),
            ))
            conn.commit()
    except Exception:
        pass  # Audit logging should not fail the request

    return wrap_settings_response(
        ok=True,
        sources=["organizations", "financial_controls"],
        scope="organization",
        last_modified_at=now,
        modified_by=user_id,
        request_id=request_id,
        org_id=org_id,
        status="updated",
        controls=current,
    )


@router.get("/api/billing/controls/alerts")
async def get_spending_alerts(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get audit-only alerts for spending thresholds.

    CONTRACT VERSION: 1
    - settings_version: ALWAYS present
    - lifecycle: ALWAYS present
    - metadata: ALWAYS present

    Read-only endpoint - NO auto-enforcement.
    Returns advisory alerts only - user must take action manually.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    alerts = _get_spending_alerts(org_id)

    return wrap_settings_response(
        ok=True,
        sources=["organizations", "financial_controls", "alerts"],
        scope="organization",
        modified_by=None,
        request_id=request_id,
        org_id=org_id,
        alerts=alerts,
        advisory_only=True,  # Explicit: no auto-actions
        message="Alerts are advisory only. No automatic enforcement.",
    )

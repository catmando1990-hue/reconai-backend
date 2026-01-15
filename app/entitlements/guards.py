# app/entitlements/guards.py
# STEP 5 — Entitlement Guards
# Functions to gate specific features by tier.
# Returns structured errors with request_id.

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request

from app.db import DB_PATH
from .tiers import get_tier_limits, require_entitlement
from .audit import log_entitlement_check


def _count_exports_today(user_id: str) -> int:
    """Count user's exports in the last 24 hours."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            cursor = conn.execute("""
                SELECT COUNT(*) FROM audit_logs
                WHERE user_id = ?
                AND action = 'DATA_EXPORT'
                AND timestamp >= ?
            """, (user_id, cutoff))
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def guard_export(
    user_id: str,
    org_id: Optional[str],
    tier: str,
    export_type: str,
    *,
    request: Optional[Request] = None,
) -> None:
    """
    Guard export access by tier.
    Raises HTTPException if not allowed.
    Logs entitlement check to audit.
    """
    # Check base entitlement
    limits = require_entitlement(tier, "exports", request=request)

    # Check daily export limit
    exports_today = _count_exports_today(user_id)
    if exports_today >= limits.export_limit_per_day:
        request_id = None
        if request:
            request_id = getattr(request.state, "request_id", None)

        # Log the denial
        log_entitlement_check(
            user_id=user_id,
            org_id=org_id,
            feature="exports",
            tier=tier,
            allowed=False,
            reason="daily_limit_exceeded",
            metadata={"exports_today": exports_today, "limit": limits.export_limit_per_day},
        )

        error_detail = {
            "error": "EXPORT_LIMIT_EXCEEDED",
            "feature": "exports",
            "current_tier": tier,
            "exports_today": exports_today,
            "daily_limit": limits.export_limit_per_day,
            "message": f"You have reached your daily export limit ({limits.export_limit_per_day} exports). Upgrade for more.",
            "upgrade_to": "pro" if tier in ("free", "starter") else None,
            "upgrade_url": "/settings/billing",
        }

        if request_id:
            error_detail["request_id"] = request_id

        raise HTTPException(status_code=429, detail=error_detail)

    # Log successful entitlement check
    log_entitlement_check(
        user_id=user_id,
        org_id=org_id,
        feature="exports",
        tier=tier,
        allowed=True,
        reason=None,
        metadata={"export_type": export_type, "exports_today": exports_today},
    )


def guard_signals_depth(
    user_id: str,
    org_id: Optional[str],
    tier: str,
    requested_limit: int,
    *,
    request: Optional[Request] = None,
) -> int:
    """
    Guard signals depth by tier.
    Returns the effective limit (capped by tier).
    Does NOT raise — just caps the limit.
    """
    limits = get_tier_limits(tier)
    effective_limit = min(requested_limit, limits.signals_depth)

    # Log if limit was capped
    was_capped = requested_limit > limits.signals_depth
    log_entitlement_check(
        user_id=user_id,
        org_id=org_id,
        feature="signals_depth",
        tier=tier,
        allowed=True,
        reason="capped" if was_capped else None,
        metadata={
            "requested": requested_limit,
            "effective": effective_limit,
            "tier_max": limits.signals_depth,
        },
    )

    return effective_limit


def guard_summary_access(
    user_id: str,
    org_id: Optional[str],
    tier: str,
    *,
    request: Optional[Request] = None,
) -> None:
    """
    Guard summary access by tier.
    Raises HTTPException if not allowed.
    """
    limits = require_entitlement(tier, "summary", request=request)

    log_entitlement_check(
        user_id=user_id,
        org_id=org_id,
        feature="summary",
        tier=tier,
        allowed=True,
        reason=None,
        metadata={},
    )

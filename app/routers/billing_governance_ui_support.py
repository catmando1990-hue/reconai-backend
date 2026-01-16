# app/routers/billing_governance_ui_support.py
"""
ReconAI Billing — Governance UI Support (Read-Only Helpers)

Endpoints:
- GET /api/billing/governance/filters - Get available filter options
- GET /api/billing/governance/diffs - Get billing state change history
- GET /api/billing/governance/export-history - Get export audit trail

Requirements:
- Auth via get_current_context (Depends injection)
- Read-only (no mutations)
- RBAC: view_status permission required
- Manual invocation only (no polling)
- Structured responses with request_id
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing-governance"])


def _get_billing_change_history(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get billing state change history from audit log."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT id, action, actor, metadata, created_at
            FROM audit_log
            WHERE (action LIKE 'BILLING_%' OR action LIKE 'billing_%')
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "action": row[1],
                "actor": row[2],
                "metadata": row[3],
                "created_at": row[4],
            })
        return results


def _get_export_history(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get export audit trail from audit log."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT id, action, actor, metadata, created_at
            FROM audit_log
            WHERE action LIKE '%EXPORT%'
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "action": row[1],
                "actor": row[2],
                "metadata": row[3],
                "created_at": row[4],
            })
        return results


@router.get("/api/billing/governance/filters")
async def get_governance_filters(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get available filter options for governance UI.

    Read-only endpoint - no mutations.
    Returns filter options for actions, date ranges, actors.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Get distinct action types from audit log
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT DISTINCT action FROM audit_log
            WHERE action LIKE 'BILLING_%' OR action LIKE 'billing_%'
            ORDER BY action
        """)
        action_types = [row[0] for row in cursor.fetchall()]

    return {
        "request_id": request_id,
        "org_id": org_id,
        "filters": {
            "action_types": action_types,
            "date_range_presets": [
                {"label": "Last 24 hours", "value": "24h"},
                {"label": "Last 7 days", "value": "7d"},
                {"label": "Last 30 days", "value": "30d"},
                {"label": "Last 90 days", "value": "90d"},
                {"label": "All time", "value": "all"},
            ],
            "sort_options": [
                {"label": "Newest first", "value": "desc"},
                {"label": "Oldest first", "value": "asc"},
            ],
        },
    }


@router.get("/api/billing/governance/diffs")
async def get_billing_diffs(
    ctx: AuthContext = Depends(get_current_context),
    action_filter: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """
    Get billing state change history (diffs).

    Read-only endpoint - no mutations.
    Returns audit trail of billing changes with metadata.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Get billing change history
    with sqlite3.connect(DB_PATH) as conn:
        if action_filter:
            cursor = conn.execute("""
                SELECT id, action, actor, metadata, created_at
                FROM audit_log
                WHERE (action LIKE 'BILLING_%' OR action LIKE 'billing_%')
                AND action = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (action_filter, limit))
        else:
            cursor = conn.execute("""
                SELECT id, action, actor, metadata, created_at
                FROM audit_log
                WHERE action LIKE 'BILLING_%' OR action LIKE 'billing_%'
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

        diffs = []
        for row in cursor.fetchall():
            diffs.append({
                "id": row[0],
                "action": row[1],
                "actor": row[2],
                "metadata": row[3],
                "created_at": row[4],
            })

    return {
        "request_id": request_id,
        "org_id": org_id,
        "diffs": diffs,
        "count": len(diffs),
    }


@router.get("/api/billing/governance/export-history")
async def get_export_history(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """
    Get export audit trail.

    Read-only endpoint - no mutations.
    Returns history of all billing-related exports.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    exports = _get_export_history(org_id, limit)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "exports": exports,
        "count": len(exports),
    }

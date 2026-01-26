# app/routers/retention.py
# Phase 74 — Data Retention & Export Controls
# Phase 5.1 — GET /api/retention?scope=evidence (P1 Endpoint)

import sqlite3
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import Optional

from app.models.retention import RetentionPolicy
from app.auth_context import get_current_organization_id
from app.db import get_db_connection

router = APIRouter(prefix='/api/retention', tags=['retention'])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


# =============================================================================
# PHASE 5.1: P1 ENDPOINT — GET /api/retention?scope=evidence
# =============================================================================
# READ-ONLY endpoint backed by retention_policies table
# - Returns policies for scope='evidence' only
# - If scope != 'evidence', returns empty list
# - Org-isolated via organization_id filter

@router.get('/', tags=['retention', 'p1'])
async def get_retention_policies(
    request: Request,
    scope: str = "evidence",
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get retention policies for the organization.

    Phase 5.1 P1 Endpoint — READ-ONLY

    Query Parameters:
        scope: Filter by policy scope (default: 'evidence')
               If scope != 'evidence', returns empty list

    Returns:
        items: List of retention policies
        request_id: UUID for request tracing
    """
    request_id = _get_request_id(request)

    # If scope is not 'evidence', return empty list per spec
    if scope != "evidence":
        return {"items": [], "request_id": request_id}

    sql = """
        SELECT
            policy_id,
            scope,
            policy_name,
            retention_days,
            enforced_from
        FROM retention_policies
        WHERE organization_id = ?
          AND scope = 'evidence'
        ORDER BY enforced_from DESC
    """

    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, (organization_id,))
        rows = cursor.fetchall()
        conn.close()

        items = [dict(row) for row in rows]
        return {"items": items, "request_id": request_id}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "retention_query_failed",
                "detail": str(e),
                "request_id": request_id
            }
        )


# =============================================================================
# LEGACY ENDPOINT — /api/retention/policy (backwards compatibility)
# =============================================================================
# Note: Path changed from /retention/policy to /api/retention/policy

@router.get('/policy', response_model=RetentionPolicy)
async def get_retention_policy():
    """
    Get current data retention policy.

    Wiring placeholder. Replace with tenant-aware retention policy store.
    """
    return RetentionPolicy(
        scope='audit',
        days=365,
        updatedAt=datetime.now(timezone.utc)
    )

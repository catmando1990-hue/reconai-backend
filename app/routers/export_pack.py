# app/routers/export_pack.py
# Phase 74 — Data Retention & Export Controls
# Phase 5.3 — POST /api/export-pack (P1 Endpoint)

import sqlite3
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.models.export_pack import ExportPackRequest, ExportPackResponse
from app.auth_context import get_current_organization_id
from app.db import get_db_connection

router = APIRouter(prefix='/api/export-pack', tags=['exports'])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


# =============================================================================
# PHASE 5.3: P1 ENDPOINT — POST /api/export-pack
# =============================================================================
# MANUAL REQUEST ONLY — records intent, does NOT execute
# - Inserts one row into export_packs with status='requested'
# - No background jobs, no polling, no auto-execution
# - Returns export_pack_id for tracking

@router.post('/', tags=['exports', 'p1'])
async def create_export_pack_request(
    request: Request,
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Request an export pack for the organization.

    Phase 5.3 P1 Endpoint — MANUAL REQUEST ONLY

    Behavior:
        - Records request intent with status='requested'
        - Does NOT execute export
        - Does NOT trigger background jobs
        - Returns export_pack_id for tracking

    Returns:
        export_pack_id: Integer ID of the created request
        request_id: UUID for request tracing
    """
    request_id = _get_request_id(request)

    # UTC ISO-8601 timestamp
    requested_at = datetime.now(timezone.utc).isoformat()

    sql = """
        INSERT INTO export_packs (
            organization_id,
            status,
            requested_at
        ) VALUES (?, 'requested', ?)
    """

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (organization_id, requested_at))
        conn.commit()

        # Get the auto-incremented ID
        export_pack_id = cursor.lastrowid
        conn.close()

        return {
            "export_pack_id": export_pack_id,
            "request_id": request_id
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "export_pack_request_failed",
                "detail": str(e),
                "request_id": request_id
            }
        )


# =============================================================================
# LEGACY ENDPOINT — /api/export-pack/request (backwards compatibility)
# =============================================================================
# Note: Path changed from /exports/request to /api/export-pack/request

@router.post('/request', response_model=ExportPackResponse)
async def request_export_pack_legacy(payload: ExportPackRequest):
    """
    Request an export pack for audit/evidence/policy data.

    Server-side generation stub. Replace with async job + signed URL store.
    """
    return ExportPackResponse(
        requestId='exp_1',
        status='queued'
    )

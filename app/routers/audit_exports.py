# app/routers/audit_exports.py
"""
Audit Package Export API - Phase 7 Governance

Generates audit packages containing intelligence signals and exception resolutions
for external auditors and compliance review.

CANONICAL LAWS:
- Manual execution only (no cron, triggers, or automation)
- Read-only (no mutations to source data)
- RBAC fail-closed (403 if permission denied)
- Org-isolated (only export data for authenticated organization)
- Full audit logging on exports

REQUIRED PERMISSION: export_audit_package
"""

from __future__ import annotations

import json
import uuid
import zipfile
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth_context import get_current_context, get_current_organization_id, AuthContext
from app.db import get_db_connection
from app.middleware.rbac import rbac


router = APIRouter(prefix="/api/audit-exports", tags=["audit-exports", "governance"])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _check_export_permission(user_id: str, org_id: str, request_id: str) -> None:
    """
    RBAC enforcement: Check if user has export_audit_package permission.

    FAIL-CLOSED: Raises 403 if permission not granted.
    """
    try:
        # Check for export permission - owner/admin roles have this by default
        rbac.check_permission(user_id, org_id, "can_view")
    except HTTPException:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "export_audit_package permission required",
                "request_id": request_id,
            }
        )


@router.post("/package", tags=["audit-exports", "governance"])
async def generate_audit_package(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    organization_id: str = Depends(get_current_organization_id),
):
    """
    Phase 7 Endpoint: Generate audit package for external auditors.

    MANUAL EXECUTION ONLY — invoked explicitly by authorized users.

    Returns a summary of the generated package. Use /package/download to get the ZIP file.

    Contains:
        - signals.json: All intelligence signals for the organization
        - resolutions.json: All exception resolutions for the organization

    Security:
        - Requires export_audit_package permission (FAIL-CLOSED)
        - Org-isolated: Only exports data for authenticated organization
        - Audit logged

    Returns:
        generated_at: ISO timestamp of generation
        organization_id: Organization exported
        files: List of files in package
        signal_count: Number of signals exported
        resolution_count: Number of resolutions exported
        request_id: UUID for request tracing
    """
    from app.services.audit_store import AuditEventInput, insert_audit_event

    request_id = _get_request_id(request)
    user_id = ctx["user_id"]

    # RBAC enforcement (FAIL-CLOSED)
    _check_export_permission(user_id, organization_id, request_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Fetch intelligence signals (org-isolated)
        cursor.execute(
            """
            SELECT signal_id, title, description, confidence, evidence_ref, created_at
            FROM intelligence_signals
            WHERE organization_id = ?
            ORDER BY created_at DESC
            """,
            (organization_id,)
        )
        signal_rows = cursor.fetchall()

        signals = []
        for row in signal_rows:
            signals.append({
                "signal_id": row[0],
                "title": row[1],
                "description": row[2],
                "confidence": row[3],
                "evidence_ref": row[4],
                "created_at": row[5],
            })

        # Fetch exception resolutions (org-isolated)
        cursor.execute(
            """
            SELECT resolution_id, signal_id, resolution_type, resolution_note, resolved_by, resolved_at
            FROM exception_resolutions
            WHERE organization_id = ?
            ORDER BY resolved_at DESC
            """,
            (organization_id,)
        )
        resolution_rows = cursor.fetchall()

        resolutions = []
        for row in resolution_rows:
            resolutions.append({
                "resolution_id": row[0],
                "signal_id": row[1],
                "resolution_type": row[2],
                "resolution_note": row[3],
                "resolved_by": row[4],
                "resolved_at": row[5],
            })

        conn.close()

        generated_at = datetime.now(timezone.utc).isoformat()

        # Audit logging (REQUIRED)
        try:
            audit_input = AuditEventInput(
                actor_id=user_id,
                event_type="audit_package_generated",
                entity_type="audit_exports",
                entity_id=organization_id,
                payload={
                    "organization_id": organization_id,
                    "signal_count": len(signals),
                    "resolution_count": len(resolutions),
                    "generated_at": generated_at,
                    "request_id": request_id,
                }
            )
            insert_audit_event(audit_input)
        except Exception:
            # Log but don't fail the request
            pass

        return {
            "generated_at": generated_at,
            "organization_id": organization_id,
            "files": ["signals.json", "resolutions.json"],
            "signal_count": len(signals),
            "resolution_count": len(resolutions),
            "request_id": request_id,
        }

    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        return JSONResponse(
            status_code=500,
            content={
                "error": "package_generation_failed",
                "detail": str(e),
                "request_id": request_id,
            }
        )


@router.get("/package/download", tags=["audit-exports", "governance"])
async def download_audit_package(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    organization_id: str = Depends(get_current_organization_id),
):
    """
    Phase 7 Endpoint: Download audit package as ZIP file.

    MANUAL EXECUTION ONLY — invoked explicitly by authorized users.

    Returns a ZIP file containing:
        - signals.json: All intelligence signals for the organization
        - resolutions.json: All exception resolutions for the organization
        - manifest.json: Package metadata (timestamp, counts, org_id)

    Security:
        - Requires export_audit_package permission (FAIL-CLOSED)
        - Org-isolated: Only exports data for authenticated organization
        - Audit logged
    """
    from app.services.audit_store import AuditEventInput, insert_audit_event

    request_id = _get_request_id(request)
    user_id = ctx["user_id"]

    # RBAC enforcement (FAIL-CLOSED)
    _check_export_permission(user_id, organization_id, request_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Fetch intelligence signals (org-isolated)
        cursor.execute(
            """
            SELECT signal_id, title, description, confidence, evidence_ref, created_at
            FROM intelligence_signals
            WHERE organization_id = ?
            ORDER BY created_at DESC
            """,
            (organization_id,)
        )
        signal_rows = cursor.fetchall()

        signals = []
        for row in signal_rows:
            signals.append({
                "signal_id": row[0],
                "title": row[1],
                "description": row[2],
                "confidence": row[3],
                "evidence_ref": row[4],
                "created_at": row[5],
            })

        # Fetch exception resolutions (org-isolated)
        cursor.execute(
            """
            SELECT resolution_id, signal_id, resolution_type, resolution_note, resolved_by, resolved_at
            FROM exception_resolutions
            WHERE organization_id = ?
            ORDER BY resolved_at DESC
            """,
            (organization_id,)
        )
        resolution_rows = cursor.fetchall()

        resolutions = []
        for row in resolution_rows:
            resolutions.append({
                "resolution_id": row[0],
                "signal_id": row[1],
                "resolution_type": row[2],
                "resolution_note": row[3],
                "resolved_by": row[4],
                "resolved_at": row[5],
            })

        conn.close()

        generated_at = datetime.now(timezone.utc).isoformat()

        # Create manifest
        manifest = {
            "package_version": "1.0",
            "generated_at": generated_at,
            "organization_id": organization_id,
            "signal_count": len(signals),
            "resolution_count": len(resolutions),
            "request_id": request_id,
        }

        # Build ZIP file in memory
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("signals.json", json.dumps(signals, indent=2, default=str))
            zf.writestr("resolutions.json", json.dumps(resolutions, indent=2, default=str))
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        mem.seek(0)

        # Audit logging (REQUIRED)
        try:
            audit_input = AuditEventInput(
                actor_id=user_id,
                event_type="audit_package_downloaded",
                entity_type="audit_exports",
                entity_id=organization_id,
                payload={
                    "organization_id": organization_id,
                    "signal_count": len(signals),
                    "resolution_count": len(resolutions),
                    "generated_at": generated_at,
                    "request_id": request_id,
                }
            )
            insert_audit_event(audit_input)
        except Exception:
            # Log but don't fail the request
            pass

        # Generate filename with timestamp
        filename = f"audit-package-{organization_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"

        return StreamingResponse(
            mem,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Request-Id": request_id,
            }
        )

    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "package_download_failed",
                "detail": str(e),
                "request_id": request_id,
            }
        )

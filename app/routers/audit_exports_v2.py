# app/routers/audit_exports_v2.py
"""
Audit Export v2 API - Evidence-Grade Financial Export Bundle

Generates comprehensive audit packages containing statements, asset snapshots,
and liabilities data as a streamed ZIP file for compliance and audit purposes.

CANONICAL LAWS:
- Manual execution only (no cron, triggers, or automation)
- Read-only (no mutations to source data)
- No new Plaid calls (uses stored/derived data only)
- RBAC fail-closed (403 if permission denied)
- Org-isolated (only export data for authenticated organization)
- Full audit logging on exports
- No background workers or schedulers

ZIP STRUCTURE:
    audit-export-{org_id}-{utc_timestamp}.zip
    ├─ statements/
    │  └─ statements.json
    ├─ assets/
    │  └─ asset_snapshot.json
    ├─ liabilities/
    │  └─ liabilities.json
    ├─ manifest.json
    └─ hashes.json

REQUIRED PERMISSION: admin or org:admin
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth_context import get_current_context, get_current_organization_id, AuthContext
from app.schemas.audit_export_v2 import AuditExportV2Request
from app.services.audit_export_builder_v2 import (
    build_audit_export_v2,
    get_export_preview,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit-exports", tags=["audit-exports-v2", "governance"])


# =============================================================================
# AUDIT EVENT CONSTANTS
# =============================================================================

# These events are logged for audit export v2 operations
AUDIT_EVENT_V2_GENERATED = "audit_export_v2_generated"
AUDIT_EVENT_V2_DOWNLOADED = "audit_export_v2_downloaded"
AUDIT_EVENT_V2_ACCESS_DENIED = "audit_export_v2_access_denied"
AUDIT_EVENT_V2_PREVIEW = "audit_export_v2_preview"


# =============================================================================
# HELPERS
# =============================================================================

def _validate_request_id(request_id: Optional[str]) -> str:
    """Validate X-Request-ID header. FAIL-CLOSED: Generate if missing."""
    if request_id:
        try:
            uuid.UUID(request_id)
            return request_id
        except (ValueError, TypeError):
            pass
    return f"req_{uuid.uuid4().hex[:16]}"


def _build_error_response(
    status_code: int,
    error: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    """Build error JSONResponse with canonical envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "data": {},
            "error": error,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Request-ID": request_id},
    )


def _assert_admin(ctx: AuthContext, request_id: str) -> None:
    """
    Ensure user has admin privileges (FAIL-CLOSED).

    Accepts:
    - admin role
    - org:admin role
    - owner role

    Raises HTTPException 403 if not authorized.
    """
    clerk_metadata = ctx.get("clerk_metadata") or {}
    clerk_role = clerk_metadata.get("role", "")

    # Check Clerk JWT role
    if clerk_role in ["admin", "org:admin", "owner"]:
        return

    # Check database permissions
    permissions = ctx.get("permissions")
    if permissions:
        db_role = permissions.get("role", "")
        if db_role in ["admin", "owner"]:
            return

    raise HTTPException(
        status_code=403,
        detail={
            "error": "permission_denied",
            "message": "Admin access required. Only admin or org:admin roles can generate audit exports.",
            "request_id": request_id,
        }
    )


def _log_audit_event(
    user_id: str,
    organization_id: str,
    event_type: str,
    request_id: str,
    payload: dict,
) -> None:
    """
    Log audit event for export operations.

    Non-blocking: errors are logged but don't fail the request.
    """
    from app.services.audit_store import AuditEventInput, insert_audit_event

    try:
        audit_input = AuditEventInput(
            actor_id=user_id,
            event_type=event_type,
            entity_type="audit_exports_v2",
            entity_id=organization_id,
            payload={
                **payload,
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        insert_audit_event(audit_input)
    except Exception as e:
        logger.warning(f"Audit logging failed for {event_type}: {e}")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/v2", tags=["audit-exports-v2", "governance"])
async def generate_audit_export_v2(
    request: Request,
    payload: Optional[AuditExportV2Request] = None,
    ctx: AuthContext = Depends(get_current_context),
    organization_id: str = Depends(get_current_organization_id),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> StreamingResponse:
    """
    Generate Audit Export v2 - Evidence-Grade Financial Export Bundle.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND WORKERS - assembled in-memory during request.
    NO PLAID CALLS - uses stored/derived data only.
    NO TEMP FILES - streams directly to client.

    ZIP STRUCTURE:
        audit-export-{org_id}-{utc_timestamp}.zip
        ├─ statements/
        │  └─ statements.json
        ├─ assets/
        │  └─ asset_snapshot.json
        ├─ liabilities/
        │  └─ liabilities.json
        ├─ manifest.json
        └─ hashes.json

    Data Sources (LOCAL ONLY):
        - Statements: Phase 8A stored data from database
        - Assets: Derived from stored transaction data
        - Liabilities: Derived from stored transaction data

    Security:
        - Requires admin or org:admin role (FAIL-CLOSED)
        - Org-isolated: Only exports data for authenticated organization
        - Audit logged: audit_export_v2_generated, audit_export_v2_downloaded
        - Structured error envelope with request_id

    Response Headers:
        - X-Request-ID: Request trace identifier
        - X-Export-Manifest-Hash: SHA-256 of manifest.json
        - Content-Disposition: Deterministic filename

    Request Body (optional):
        - include_statements: Include statements section (default: true)
        - include_assets: Include assets section (default: true)
        - include_liabilities: Include liabilities section (default: true)
    """
    request_id = _validate_request_id(x_request_id)
    user_id = ctx["user_id"]

    # Parse options
    include_statements = True
    include_assets = True
    include_liabilities = True
    if payload:
        include_statements = payload.include_statements
        include_assets = payload.include_assets
        include_liabilities = payload.include_liabilities

    # ==========================================================================
    # RBAC ENFORCEMENT (FAIL-CLOSED)
    # ==========================================================================
    try:
        _assert_admin(ctx, request_id)
    except HTTPException as e:
        _log_audit_event(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUDIT_EVENT_V2_ACCESS_DENIED,
            request_id=request_id,
            payload={
                "reason": "insufficient_permissions",
                "org_id": organization_id,
            }
        )
        raise e

    # ==========================================================================
    # AUDIT LOG: GENERATION STARTED
    # ==========================================================================
    _log_audit_event(
        user_id=user_id,
        organization_id=organization_id,
        event_type=AUDIT_EVENT_V2_GENERATED,
        request_id=request_id,
        payload={
            "org_id": organization_id,
            "include_statements": include_statements,
            "include_assets": include_assets,
            "include_liabilities": include_liabilities,
        }
    )

    try:
        # ==========================================================================
        # BUILD ZIP IN MEMORY (via builder service)
        # ==========================================================================
        result = build_audit_export_v2(
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            include_statements=include_statements,
            include_assets=include_assets,
            include_liabilities=include_liabilities,
        )

        # Get manifest hash for header
        manifest_hash = result.file_hashes.get("manifest.json", "")

        # ==========================================================================
        # AUDIT LOG: DOWNLOAD
        # ==========================================================================
        _log_audit_event(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUDIT_EVENT_V2_DOWNLOADED,
            request_id=request_id,
            payload={
                "org_id": organization_id,
                "filename": result.filename,
                "manifest_hash": manifest_hash[:16] + "..." if manifest_hash else None,
                "included_sections": result.manifest.get("included_sections", []),
                "counts": result.manifest.get("counts", {}),
            }
        )

        # ==========================================================================
        # STREAM RESPONSE
        # ==========================================================================
        return StreamingResponse(
            result.zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{result.filename}"',
                "X-Request-ID": request_id,
                "X-Export-Manifest-Hash": manifest_hash,
                "X-Export-Type": "audit_export_v2",
            }
        )

    except Exception as e:
        logger.error(f"Audit export v2 failed: {e}")
        return _build_error_response(
            status_code=500,
            error="export_generation_failed",
            message="Failed to generate audit export. Please try again.",
            request_id=request_id,
        )


@router.get("/v2/preview", tags=["audit-exports-v2", "governance"])
async def preview_audit_export_v2(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    organization_id: str = Depends(get_current_organization_id),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Preview what would be included in an Audit Export v2.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO PLAID CALLS - uses stored/derived data only.

    Returns a summary of available data without generating the ZIP file.
    Useful for checking what data is available before generating the export.

    Security:
        - Requires admin or org:admin role (FAIL-CLOSED)
        - Org-isolated: Only previews data for authenticated organization
        - Audit logged: audit_export_v2_preview
    """
    request_id = _validate_request_id(x_request_id)
    user_id = ctx["user_id"]

    # RBAC enforcement (FAIL-CLOSED)
    try:
        _assert_admin(ctx, request_id)
    except HTTPException as e:
        raise e

    try:
        # Get preview data (no ZIP generation)
        preview_data = get_export_preview(organization_id)

        # Audit log
        _log_audit_event(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUDIT_EVENT_V2_PREVIEW,
            request_id=request_id,
            payload={
                "org_id": organization_id,
            }
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "data": preview_data,
                "message": "Audit export v2 preview generated",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Audit export v2 preview failed: {e}")
        return _build_error_response(
            status_code=500,
            error="preview_failed",
            message="Failed to generate preview. Please try again.",
            request_id=request_id,
        )

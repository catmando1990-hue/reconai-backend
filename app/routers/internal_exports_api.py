# app/routers/internal_exports_api.py
"""
Internal Admin API for S3 Export Lifecycle Management

EXECUTION MODEL:
- Manual execution only (admin-triggered or cron-scheduled)
- NO polling loops
- NO background timers in web handlers
- Idempotent and safe to run multiple times

SECURITY:
- Admin-only access
- No user-facing endpoints
- Audit logging for all operations
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional as OptionalType
from datetime import datetime
import logging

from app.auth_context import get_current_context, AuthContext
from app.utils.response_envelope import ok, error, generate_request_id
from app.services.s3_exports import (
    run_expiration_job,
    get_expired_exports,
    get_cloudfront_status,
    get_export_provenance,
    get_export_by_id,
    create_export_record,
    DEFAULT_RETENTION_DAYS,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_EXPIRED,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/exports", tags=["Internal - Export Lifecycle"])


# =============================================================================
# ACCESS CONTROL
# =============================================================================

def _assert_admin(ctx: AuthContext):
    """
    Ensure the user has admin privileges.

    Checks both Clerk metadata and database role.
    """
    clerk_metadata = ctx.get("clerk_metadata") or {}
    clerk_role = clerk_metadata.get("role", "")
    if clerk_role in ["admin", "org:admin", "owner"]:
        return

    permissions = ctx.get("permissions")
    if permissions:
        db_role = permissions.get("role", "")
        if db_role in ["admin", "owner"]:
            return

    raise HTTPException(
        status_code=403,
        detail="Admin access required"
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/expire")
async def trigger_export_expiration(
    limit: int = Query(100, ge=1, le=1000, description="Maximum exports to process"),
    dry_run: bool = Query(False, description="Preview what would be expired without making changes"),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Trigger export expiration job.

    POST /internal/exports/expire

    Manually triggers the export lifecycle enforcement:
    1. Finds exports with status='ready' that have passed their expiration
    2. Deletes the S3 objects
    3. Updates DB status to 'expired'

    EXECUTION MODEL:
    - Manual trigger only (admin or cron)
    - Idempotent - safe to run multiple times
    - One export failure does not block others

    RETENTION POLICY:
    - Uses expires_at if set on the export
    - Falls back to created_at + DEFAULT_RETENTION_DAYS (30 days)
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        logger.info(f"Admin {ctx.get('user_id')} triggered export expiration: limit={limit}, dry_run={dry_run}")

        # Run the expiration job
        result = run_expiration_job(limit=limit, dry_run=dry_run)

        # Add admin context to result
        result["triggered_by"] = ctx.get("user_id")
        result["request_id"] = request_id

        return ok(
            data=result,
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Export expiration job failed: {e}")
        return error(
            message="Export expiration job failed",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.get("/expire/preview")
async def preview_expired_exports(
    limit: int = Query(100, ge=1, le=1000, description="Maximum exports to return"),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Preview exports that would be expired.

    GET /internal/exports/expire/preview

    Read-only endpoint to see what exports are due for expiration.
    Does not make any changes.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        expired = get_expired_exports(limit=limit)

        return ok(
            data={
                "total_expired": len(expired),
                "retention_policy_days": DEFAULT_RETENTION_DAYS,
                "exports": [e.to_dict() for e in expired],
                "note": "Use POST /internal/exports/expire to process these exports",
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to preview expired exports: {e}")
        return error(
            message="Failed to preview expired exports",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.get("/stats")
async def get_export_stats(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of exports per page"),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get paginated list of exports.

    GET /internal/exports/stats

    Query params:
    - page: Page number (default: 1)
    - page_size: Number of exports per page (default: 20, max: 100)

    Returns paginated exports list with total count.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        import sqlite3
        from app.db import DB_PATH

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Get total count
            count_cursor = conn.execute("SELECT COUNT(*) as total FROM s3_exports")
            total_count = count_cursor.fetchone()["total"]

            # Get paginated exports
            offset = (page - 1) * page_size
            cursor = conn.execute(
                """
                SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
                FROM s3_exports
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            rows = cursor.fetchall()

        exports = [
            {
                "id": row["id"],
                "org_id": row["org_id"],
                "user_id": row["user_id"],
                "s3_key": row["s3_key"],
                "filename": row["filename"],
                "file_type": row["file_type"],
                "size_bytes": row["size_bytes"],
                "status": row["status"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
                "expires_at": row["expires_at"],
            }
            for row in rows
        ]

        return ok(
            data={
                "exports": exports,
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to get export stats: {e}")
        return error(
            message="Failed to get export stats",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


class AuditPackageRequest(BaseModel):
    """Request body for creating an audit package export."""
    organization_id: OptionalType[str] = None


@router.post("/audit-package")
async def create_audit_package_export(
    body: AuditPackageRequest = None,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Create an audit package export job.

    POST /internal/exports/audit-package

    Request body (optional):
    - organization_id: Organization ID to create export for (defaults to user's org)

    Creates a row in the s3_exports table with status='pending' and
    queues the export job for processing.

    Returns the export_id and status.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        user_id = ctx.get("user_id")
        # Use body.organization_id if provided, otherwise fall back to context
        org_id = (body.organization_id if body else None) or ctx.get("organization_id")

        if not org_id:
            return error(
                message="organization_id required in request body or context",
                request_id=request_id,
                status_code=400,
            )

        from uuid import uuid4

        # Generate export ID and S3 key
        export_id = f"exp_{uuid4().hex[:16]}"
        filename = f"audit-package-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
        s3_key = f"exports/org_{org_id}/user_{user_id}/export_{export_id}.zip"

        # Create the export record with pending status
        export = create_export_record(
            org_id=org_id,
            user_id=user_id,
            s3_key=s3_key,
            filename=filename,
            file_type="application/zip",
            status=STATUS_PENDING,
        )

        logger.info(f"Admin {user_id} created audit package export: id={export.id}, org={org_id}")

        return ok(
            data={
                "export_id": export.id,
                "status": STATUS_PENDING,
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to create audit package export: {e}")
        return error(
            message="Failed to create audit package export",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.get("/cloudfront/status")
async def get_cloudfront_configuration_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get CloudFront configuration status for diagnostics.

    GET /internal/exports/cloudfront/status

    Returns CloudFront configuration status:
    - Whether CloudFront is configured
    - Distribution URL (truncated)
    - Key pair ID
    - Whether private key is present

    NOTE: Private key value is never returned.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        status = get_cloudfront_status()

        return ok(
            data={
                "cloudfront": status,
                "mode": "cloudfront" if status["configured"] else "s3_fallback",
                "note": "CloudFront configured" if status["configured"] else "Using S3 presigned URLs (dev mode)",
                "timestamp": datetime.utcnow().isoformat(),
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to get CloudFront status: {e}")
        return error(
            message="Failed to get CloudFront status",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )


@router.get("/{export_id}/provenance")
async def get_export_provenance_chain(
    export_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get the provenance chain for an export.

    GET /internal/exports/{export_id}/provenance

    Returns the list of evidence records linked to this export,
    enabling traceability from export -> evidence -> source data.

    TRACEABILITY:
    - Links exports to their source evidence records
    - Evidence types: evidence_refs, audit_events, etc.
    - Immutable: links are INSERT-only, never modified

    Response:
    - export_id: The export ID
    - export_type: File type of the export
    - status: Export status
    - created_at: Creation timestamp
    - evidence_links: List of evidence links
    - total_evidence_count: Count of linked evidence records
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        # Get the export record
        export = get_export_by_id(export_id)
        if not export:
            return error(
                message=f"Export not found: {export_id}",
                request_id=request_id,
                status_code=404,
            )

        # Get the provenance chain
        provenance = get_export_provenance(export_id)

        return ok(
            data={
                "export_id": export.id,
                "export_type": export.file_type,
                "status": export.status,
                "created_at": export.created_at,
                "evidence_links": [link.to_dict() for link in provenance],
                "total_evidence_count": len(provenance),
            },
            request_id=request_id,
        )

    except HTTPException as e:
        return error(
            message=str(e.detail) if isinstance(e.detail, str) else "Forbidden",
            request_id=request_id,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to get export provenance: {e}")
        return error(
            message="Failed to get export provenance",
            request_id=request_id,
            status_code=500,
            details={"exception": str(e)[:200]},
        )

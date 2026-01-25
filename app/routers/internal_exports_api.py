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
from datetime import datetime
import logging

from app.auth_context import get_current_context, AuthContext
from app.utils.response_envelope import ok, error, generate_request_id
from app.services.s3_exports import (
    run_expiration_job,
    get_expired_exports,
    get_cloudfront_status,
    DEFAULT_RETENTION_DAYS,
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
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get export lifecycle statistics.

    GET /internal/exports/stats

    Returns counts by status for monitoring.
    """
    request_id = generate_request_id()

    try:
        _assert_admin(ctx)

        import sqlite3
        from app.db import DB_PATH

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM s3_exports
                GROUP BY status
                """
            )
            rows = cursor.fetchall()

        stats = {row[0]: row[1] for row in rows}

        return ok(
            data={
                "stats_by_status": stats,
                "retention_policy_days": DEFAULT_RETENTION_DAYS,
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
        logger.error(f"Failed to get export stats: {e}")
        return error(
            message="Failed to get export stats",
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

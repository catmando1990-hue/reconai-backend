# app/services/export_audit.py
"""
S3 Export Audit Logging

Records immutable audit events for the full S3 export lifecycle.

EVENTS EMITTED:
- export_created: When export is persisted to S3 and marked READY
- export_downloaded: When signed download URL is generated (URL not logged)
- export_expired: When lifecycle job expires an export

DESIGN PRINCIPLES:
- Append-only: Uses existing audit_store infrastructure
- Non-blocking: Audit failures must not break export flow
- No sensitive data: URLs, secrets, and PII are never logged
- Deterministic: Same input produces consistent audit output

CANONICAL LAWS ENFORCED:
- Evidence > Explanation: Raw event data, not summaries
- Manual > Automatic: Advisory logging only
- Signed > Trusted: Hash-chained via audit_store
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.audit_store import AuditEventInput, insert_audit_event

logger = logging.getLogger(__name__)

# Entity type for all export audit events
ENTITY_TYPE_EXPORT = "s3_export"

# Event types
EVENT_EXPORT_CREATED = "export_created"
EVENT_EXPORT_DOWNLOADED = "export_downloaded"
EVENT_EXPORT_EXPIRED = "export_expired"


def _emit_audit_event(
    event_type: str,
    export_id: str,
    org_id: str,
    user_id: str,
    request_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Internal helper to emit an audit event.

    Non-blocking: catches all exceptions and logs them without
    interrupting the calling flow.

    Args:
        event_type: Type of event (export_created, export_downloaded, export_expired)
        export_id: The export ID
        org_id: Organization ID
        user_id: User ID (or "system" for automated jobs)
        request_id: Request ID for tracing (optional)
        metadata: Additional metadata (optional, no sensitive data)

    Returns:
        True if event was recorded successfully, False otherwise
    """
    try:
        # Build payload (no sensitive data)
        payload: Dict[str, Any] = {
            "export_id": export_id,
            "org_id": org_id,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if request_id:
            payload["request_id"] = request_id

        if metadata:
            # Filter out any potentially sensitive keys
            safe_metadata = {
                k: v for k, v in metadata.items()
                if k not in ("url", "download_url", "access_token", "secret", "password", "s3_url")
            }
            payload["metadata"] = safe_metadata

        # Create audit event input
        event = AuditEventInput(
            actor_id=user_id,
            event_type=event_type,
            entity_type=ENTITY_TYPE_EXPORT,
            entity_id=export_id,
            payload=payload,
        )

        # Insert (append-only)
        insert_audit_event(event)

        logger.debug(f"Audit event recorded: {event_type} for export {export_id}")
        return True

    except Exception as e:
        # Non-blocking: log the error but don't raise
        logger.error(f"Failed to record audit event {event_type} for export {export_id}: {e}")
        return False


def log_export_created(
    export_id: str,
    org_id: str,
    user_id: str,
    request_id: Optional[str] = None,
    filename: Optional[str] = None,
    file_type: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> bool:
    """
    Log an export_created audit event.

    Called when an export is persisted to S3 and marked READY.

    Args:
        export_id: The export ID
        org_id: Organization ID
        user_id: User ID who created the export
        request_id: Request ID for tracing
        filename: Original filename (optional)
        file_type: MIME type (optional)
        size_bytes: File size (optional)

    Returns:
        True if event was recorded successfully
    """
    metadata: Dict[str, Any] = {}

    if filename:
        metadata["filename"] = filename
    if file_type:
        metadata["file_type"] = file_type
    if size_bytes is not None:
        metadata["size_bytes"] = size_bytes

    return _emit_audit_event(
        event_type=EVENT_EXPORT_CREATED,
        export_id=export_id,
        org_id=org_id,
        user_id=user_id,
        request_id=request_id,
        metadata=metadata if metadata else None,
    )


def log_export_downloaded(
    export_id: str,
    org_id: str,
    user_id: str,
    request_id: Optional[str] = None,
    expires_in_seconds: Optional[int] = None,
) -> bool:
    """
    Log an export_downloaded audit event.

    Called when a signed download URL is generated.
    NOTE: The actual URL is NOT logged for security reasons.

    Args:
        export_id: The export ID
        org_id: Organization ID
        user_id: User ID who requested the download
        request_id: Request ID for tracing
        expires_in_seconds: URL expiration time (optional)

    Returns:
        True if event was recorded successfully
    """
    metadata: Dict[str, Any] = {}

    if expires_in_seconds is not None:
        metadata["url_expires_in_seconds"] = expires_in_seconds

    return _emit_audit_event(
        event_type=EVENT_EXPORT_DOWNLOADED,
        export_id=export_id,
        org_id=org_id,
        user_id=user_id,
        request_id=request_id,
        metadata=metadata if metadata else None,
    )


def log_export_expired(
    export_id: str,
    org_id: str,
    job_run_id: Optional[str] = None,
    s3_deleted: bool = False,
    s3_error: Optional[str] = None,
) -> bool:
    """
    Log an export_expired audit event.

    Called when the lifecycle job expires an export.

    Args:
        export_id: The export ID
        org_id: Organization ID
        job_run_id: The expiration job run ID (used as request_id)
        s3_deleted: Whether the S3 object was successfully deleted
        s3_error: Error message if S3 deletion failed (optional)

    Returns:
        True if event was recorded successfully
    """
    metadata: Dict[str, Any] = {
        "s3_deleted": s3_deleted,
    }

    if s3_error:
        # Truncate error message to avoid bloating audit log
        metadata["s3_error"] = s3_error[:200] if len(s3_error) > 200 else s3_error

    return _emit_audit_event(
        event_type=EVENT_EXPORT_EXPIRED,
        export_id=export_id,
        org_id=org_id,
        user_id="system",  # Lifecycle jobs run as system
        request_id=job_run_id,
        metadata=metadata,
    )

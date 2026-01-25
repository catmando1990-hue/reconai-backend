# app/services/s3_exports.py
"""
S3 Exports Service - Secure, time-limited signed download URLs for private S3 exports.

SECURITY GUARANTEES:
- S3 objects remain private at all times
- All access is brokered by the FastAPI backend
- Signed URLs expire after configurable time (default 300 seconds)
- No public ACLs
- No bucket listing permissions
- Server-side encryption (AES-256) for all uploads

OBJECT KEY STRUCTURE:
- exports/org_{orgId}/user_{userId}/export_{exportId}.{ext}
"""

from __future__ import annotations

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from uuid import uuid4
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from app.db import DB_PATH

logger = logging.getLogger(__name__)

# Lazy import for audit logging to avoid circular imports
_audit_module = None

def _get_audit_module():
    """Lazy import of export_audit module."""
    global _audit_module
    if _audit_module is None:
        from app.services import export_audit
        _audit_module = export_audit
    return _audit_module

# =============================================================================
# CONFIGURATION
# =============================================================================

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_EXPORTS_BUCKET = os.getenv("S3_EXPORTS_BUCKET", "reconai-prod-private-exports")

# CloudFront configuration (optional - falls back to S3 presigned URLs if not set)
CLOUDFRONT_DISTRIBUTION_URL = os.getenv("CLOUDFRONT_DISTRIBUTION_URL")  # e.g., https://d1234example.cloudfront.net
CLOUDFRONT_KEY_PAIR_ID = os.getenv("CLOUDFRONT_KEY_PAIR_ID")  # e.g., K2EXAMPLE123ABC
CLOUDFRONT_PRIVATE_KEY = os.getenv("CLOUDFRONT_PRIVATE_KEY")  # Base64-encoded RSA private key

# Default URL expiration in seconds
DEFAULT_URL_EXPIRATION_SECONDS = 300

# Default retention period in days (exports expire after this time)
DEFAULT_RETENTION_DAYS = 30

# Export status values
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"


# =============================================================================
# S3 CLIENT INITIALIZATION
# =============================================================================

def _get_s3_client():
    """
    Initialize and return boto3 S3 client using environment variables.

    Raises:
        NoCredentialsError: If AWS credentials are not configured
    """
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise NoCredentialsError()

    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


# =============================================================================
# CLOUDFRONT SIGNED URL GENERATION
# =============================================================================

def _is_cloudfront_configured() -> bool:
    """Check if CloudFront is configured for signed URLs."""
    return bool(
        CLOUDFRONT_DISTRIBUTION_URL
        and CLOUDFRONT_KEY_PAIR_ID
        and CLOUDFRONT_PRIVATE_KEY
    )


def _get_cloudfront_private_key() -> bytes:
    """
    Decode and return the CloudFront private key.

    The key is expected to be base64-encoded in the environment variable.

    Returns:
        PEM-encoded private key as bytes

    Raises:
        ValueError: If private key is not configured or invalid
    """
    import base64

    if not CLOUDFRONT_PRIVATE_KEY:
        raise ValueError("CLOUDFRONT_PRIVATE_KEY not configured")

    try:
        # Decode base64-encoded key
        key_bytes = base64.b64decode(CLOUDFRONT_PRIVATE_KEY)
        return key_bytes
    except Exception as e:
        raise ValueError(f"Failed to decode CloudFront private key: {e}") from e


def _generate_cloudfront_signed_url(
    resource_path: str,
    expires_seconds: int = DEFAULT_URL_EXPIRATION_SECONDS,
) -> str:
    """
    Generate a CloudFront signed URL using canned policy.

    Args:
        resource_path: The path to the resource (e.g., /exports/org_123/file.csv)
        expires_seconds: URL expiration time in seconds

    Returns:
        Signed CloudFront URL

    Raises:
        ValueError: If CloudFront is not configured
        Exception: If signing fails
    """
    import base64
    import json
    from datetime import datetime, timezone

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not _is_cloudfront_configured():
        raise ValueError("CloudFront is not configured")

    # Build the full URL
    base_url = CLOUDFRONT_DISTRIBUTION_URL.rstrip("/")
    if not resource_path.startswith("/"):
        resource_path = f"/{resource_path}"
    url = f"{base_url}{resource_path}"

    # Calculate expiration timestamp
    expire_time = int(datetime.now(timezone.utc).timestamp()) + expires_seconds

    # Create canned policy
    # CloudFront canned policy format
    policy = {
        "Statement": [
            {
                "Resource": url,
                "Condition": {
                    "DateLessThan": {
                        "AWS:EpochTime": expire_time
                    }
                }
            }
        ]
    }

    # Serialize policy (compact JSON, no spaces)
    policy_json = json.dumps(policy, separators=(",", ":"))

    # Load private key
    private_key_pem = _get_cloudfront_private_key()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)

    # Sign the policy
    signature = private_key.sign(
        policy_json.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA1(),  # CloudFront requires SHA1 for signed URLs
    )

    # Base64 encode and make URL-safe
    def _url_safe_base64(data: bytes) -> str:
        """Encode bytes to URL-safe base64 (CloudFront format)."""
        b64 = base64.b64encode(data).decode("ascii")
        # CloudFront uses modified base64: + -> -, / -> ~, = -> _
        return b64.replace("+", "-").replace("/", "~").replace("=", "_")

    policy_b64 = _url_safe_base64(policy_json.encode("utf-8"))
    signature_b64 = _url_safe_base64(signature)

    # Build signed URL with query parameters
    signed_url = (
        f"{url}"
        f"?Policy={policy_b64}"
        f"&Signature={signature_b64}"
        f"&Key-Pair-Id={CLOUDFRONT_KEY_PAIR_ID}"
    )

    logger.info(f"Generated CloudFront signed URL for path={resource_path}, expires_in={expires_seconds}s")
    return signed_url


def get_cloudfront_status() -> dict:
    """
    Get CloudFront configuration status for diagnostics.

    Returns:
        dict with CloudFront configuration status
    """
    return {
        "configured": _is_cloudfront_configured(),
        "distribution_url": CLOUDFRONT_DISTRIBUTION_URL[:50] + "..." if CLOUDFRONT_DISTRIBUTION_URL and len(CLOUDFRONT_DISTRIBUTION_URL) > 50 else CLOUDFRONT_DISTRIBUTION_URL,
        "key_pair_id": CLOUDFRONT_KEY_PAIR_ID,
        "private_key_present": bool(CLOUDFRONT_PRIVATE_KEY),
    }


# =============================================================================
# S3 OPERATIONS
# =============================================================================

def generate_download_url(key: str, expires_seconds: int = DEFAULT_URL_EXPIRATION_SECONDS) -> str:
    """
    Generate a presigned download URL for a private S3 object.

    If CloudFront is configured, returns a CloudFront signed URL.
    Otherwise, falls back to S3 presigned URL (development only).

    Args:
        key: The S3 object key (path within bucket)
        expires_seconds: URL expiration time in seconds (default: 300)

    Returns:
        Presigned URL string (CloudFront or S3)

    Raises:
        ClientError: If S3 operation fails
        NoCredentialsError: If AWS credentials are not configured
        ValueError: If CloudFront signing fails
    """
    # Use CloudFront if configured (production)
    if _is_cloudfront_configured():
        return _generate_cloudfront_signed_url(
            resource_path=key,
            expires_seconds=expires_seconds,
        )

    # Fall back to S3 presigned URL (development only)
    logger.warning("CloudFront not configured, using S3 presigned URL (dev mode)")
    s3 = _get_s3_client()

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_EXPORTS_BUCKET,
            "Key": key,
        },
        ExpiresIn=expires_seconds,
    )

    logger.info(f"Generated S3 presigned URL for key={key}, expires_in={expires_seconds}s")
    return url


def upload_export(
    data: bytes,
    org_id: str,
    user_id: str,
    export_id: str,
    filename: str,
    content_type: str = "application/octet-stream",
) -> Tuple[str, int]:
    """
    Upload export data to S3 with server-side encryption.

    Object key structure: exports/org_{orgId}/user_{userId}/export_{exportId}.{ext}

    Args:
        data: File content as bytes
        org_id: Organization ID
        user_id: User ID
        export_id: Export ID
        filename: Original filename (used for extension)
        content_type: MIME type of the file

    Returns:
        Tuple of (s3_key, size_bytes)

    Raises:
        ClientError: If S3 upload fails
        NoCredentialsError: If AWS credentials are not configured
    """
    s3 = _get_s3_client()

    # Extract extension from filename
    ext = Path(filename).suffix or ".bin"
    if not ext.startswith("."):
        ext = f".{ext}"

    # Build S3 key with predictable structure
    s3_key = f"exports/org_{org_id}/user_{user_id}/export_{export_id}{ext}"

    # Upload with server-side encryption
    s3.put_object(
        Bucket=S3_EXPORTS_BUCKET,
        Key=s3_key,
        Body=data,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )

    size_bytes = len(data)
    logger.info(f"Uploaded export to S3: key={s3_key}, size={size_bytes} bytes")

    return s3_key, size_bytes


def create_and_upload_export(
    data: bytes,
    org_id: str,
    user_id: str,
    filename: str,
    content_type: str = "application/octet-stream",
    request_id: Optional[str] = None,
    retention_days: Optional[int] = None,
) -> S3ExportRecord:
    """
    Create a complete export: upload to S3, create DB record, and emit audit event.

    This is the recommended entry point for backend export generation flows.
    It handles the full lifecycle including audit logging.

    Args:
        data: File content as bytes
        org_id: Organization ID
        user_id: User ID who created the export
        filename: Original filename
        content_type: MIME type of the file
        request_id: Request ID for audit tracing (optional)
        retention_days: Custom retention period (optional, defaults to DEFAULT_RETENTION_DAYS)

    Returns:
        S3ExportRecord with status=ready

    Raises:
        ClientError: If S3 upload fails
        NoCredentialsError: If AWS credentials are not configured
    """
    from uuid import uuid4

    # Generate export ID
    export_id = f"exp_{uuid4().hex[:16]}"

    # Calculate expiration
    retention = retention_days if retention_days is not None else DEFAULT_RETENTION_DAYS
    expires_at = datetime.utcnow() + timedelta(days=retention)

    # Upload to S3
    s3_key, size_bytes = upload_export(
        data=data,
        org_id=org_id,
        user_id=user_id,
        export_id=export_id,
        filename=filename,
        content_type=content_type,
    )

    # Create DB record with status=ready
    now = datetime.utcnow().isoformat()
    expires_at_str = expires_at.isoformat()

    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO s3_exports (id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (export_id, org_id, user_id, s3_key, filename, content_type, size_bytes, STATUS_READY, now, now, expires_at_str),
        )
        conn.commit()

    # Emit audit event (non-blocking)
    try:
        audit = _get_audit_module()
        audit.log_export_created(
            export_id=export_id,
            org_id=org_id,
            user_id=user_id,
            request_id=request_id,
            filename=filename,
            file_type=content_type,
            size_bytes=size_bytes,
        )
    except Exception as e:
        logger.warning(f"Failed to log export_created audit event: {e}")

    logger.info(f"Export created: id={export_id}, s3_key={s3_key}, size={size_bytes} bytes")

    return S3ExportRecord(
        id=export_id,
        org_id=org_id,
        user_id=user_id,
        s3_key=s3_key,
        filename=filename,
        file_type=content_type,
        size_bytes=size_bytes,
        status=STATUS_READY,
        created_at=now,
        completed_at=now,
        expires_at=expires_at_str,
    )


def delete_export(key: str) -> bool:
    """
    Delete an export from S3.

    Handles missing objects gracefully (idempotent).

    Args:
        key: The S3 object key

    Returns:
        True if deleted or already missing

    Note:
        S3 DeleteObject is idempotent - deleting a non-existent object
        does not raise an error.
    """
    try:
        s3 = _get_s3_client()

        s3.delete_object(
            Bucket=S3_EXPORTS_BUCKET,
            Key=key,
        )

        logger.info(f"Deleted export from S3: key={key}")
        return True
    except ClientError as e:
        # Log but don't fail if object doesn't exist
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            logger.warning(f"S3 object already missing: key={key}")
            return True
        raise


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

class S3ExportRecord:
    """Represents an S3 export record from the database."""

    def __init__(
        self,
        id: str,
        org_id: str,
        user_id: str,
        s3_key: str,
        filename: str,
        file_type: str,
        size_bytes: Optional[int],
        status: str,
        created_at: str,
        completed_at: Optional[str],
        expires_at: Optional[str],
    ):
        self.id = id
        self.org_id = org_id
        self.user_id = user_id
        self.s3_key = s3_key
        self.filename = filename
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.status = status
        self.created_at = created_at
        self.completed_at = completed_at
        self.expires_at = expires_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "s3_key": self.s3_key,
            "filename": self.filename,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "expires_at": self.expires_at,
        }


def create_export_record(
    org_id: str,
    user_id: str,
    s3_key: str,
    filename: str,
    file_type: str,
    size_bytes: Optional[int] = None,
    status: str = "pending",
    expires_at: Optional[datetime] = None,
) -> S3ExportRecord:
    """
    Create a new export record in the database.

    Args:
        org_id: Organization ID
        user_id: User ID who created the export
        s3_key: S3 object key
        filename: Original filename
        file_type: MIME type or file extension
        size_bytes: File size in bytes
        status: Export status (pending, completed, failed)
        expires_at: When the export expires

    Returns:
        Created S3ExportRecord
    """
    export_id = f"exp_{uuid4().hex[:16]}"
    now = datetime.utcnow().isoformat()
    expires_at_str = expires_at.isoformat() if expires_at else None

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO s3_exports (id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (export_id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, now, expires_at_str),
        )
        conn.commit()

    return S3ExportRecord(
        id=export_id,
        org_id=org_id,
        user_id=user_id,
        s3_key=s3_key,
        filename=filename,
        file_type=file_type,
        size_bytes=size_bytes,
        status=status,
        created_at=now,
        completed_at=None,
        expires_at=expires_at_str,
    )


def get_export_by_id(export_id: str) -> Optional[S3ExportRecord]:
    """
    Get an export record by ID.

    Args:
        export_id: The export ID

    Returns:
        S3ExportRecord if found, None otherwise
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
            FROM s3_exports
            WHERE id = ?
            """,
            (export_id,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return S3ExportRecord(**dict(row))


def get_export_for_user(export_id: str, user_id: str, org_id: str) -> Optional[S3ExportRecord]:
    """
    Get an export record by ID, validating ownership.

    Args:
        export_id: The export ID
        user_id: The requesting user's ID
        org_id: The requesting user's organization ID

    Returns:
        S3ExportRecord if found and owned by user, None otherwise
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
            FROM s3_exports
            WHERE id = ? AND user_id = ? AND org_id = ?
            """,
            (export_id, user_id, org_id),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return S3ExportRecord(**dict(row))


def update_export_status(
    export_id: str,
    status: str,
    size_bytes: Optional[int] = None,
    completed_at: Optional[datetime] = None,
) -> bool:
    """
    Update an export record's status.

    Args:
        export_id: The export ID
        status: New status (pending, completed, failed)
        size_bytes: File size (if now known)
        completed_at: Completion timestamp

    Returns:
        True if updated, False if not found
    """
    completed_at_str = completed_at.isoformat() if completed_at else None

    with sqlite3.connect(DB_PATH) as conn:
        if size_bytes is not None:
            cursor = conn.execute(
                """
                UPDATE s3_exports
                SET status = ?, size_bytes = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, size_bytes, completed_at_str, export_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE s3_exports
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, completed_at_str, export_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def list_user_exports(
    user_id: str,
    org_id: str,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[S3ExportRecord]:
    """
    List exports for a user within their organization.

    Args:
        user_id: The user's ID
        org_id: The organization ID
        status: Filter by status (optional)
        limit: Maximum number of records to return

    Returns:
        List of S3ExportRecord
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        if status:
            cursor = conn.execute(
                """
                SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
                FROM s3_exports
                WHERE user_id = ? AND org_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, org_id, status, limit),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
                FROM s3_exports
                WHERE user_id = ? AND org_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, org_id, limit),
            )

        rows = cursor.fetchall()

    return [S3ExportRecord(**dict(row)) for row in rows]


def delete_export_record(export_id: str) -> bool:
    """
    Delete an export record from the database.

    Args:
        export_id: The export ID

    Returns:
        True if deleted, False if not found
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "DELETE FROM s3_exports WHERE id = ?",
            (export_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# LIFECYCLE & RETENTION ENFORCEMENT
# =============================================================================

def get_expired_exports(limit: int = 100) -> list[S3ExportRecord]:
    """
    Get exports that are ready but have passed their expiration time.

    Uses expires_at if set, otherwise calculates from created_at + retention period.

    Args:
        limit: Maximum number of records to return

    Returns:
        List of expired S3ExportRecord
    """
    now = datetime.utcnow().isoformat()
    default_expiry_threshold = (datetime.utcnow() - timedelta(days=DEFAULT_RETENTION_DAYS)).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, org_id, user_id, s3_key, filename, file_type, size_bytes, status, created_at, completed_at, expires_at
            FROM s3_exports
            WHERE status = ?
            AND (
                (expires_at IS NOT NULL AND expires_at <= ?)
                OR (expires_at IS NULL AND created_at <= ?)
            )
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (STATUS_READY, now, default_expiry_threshold, limit),
        )
        rows = cursor.fetchall()

    return [S3ExportRecord(**dict(row)) for row in rows]


def expire_export(export_id: str) -> dict:
    """
    Expire a single export: delete from S3 and update status.

    Args:
        export_id: The export ID to expire

    Returns:
        dict with result details
    """
    export = get_export_by_id(export_id)
    if not export:
        return {"export_id": export_id, "success": False, "error": "Export not found"}

    if export.status != STATUS_READY:
        return {"export_id": export_id, "success": False, "error": f"Export not in ready state: {export.status}"}

    # Delete from S3 (handles missing objects gracefully)
    s3_deleted = False
    s3_error = None
    try:
        s3_deleted = delete_export(export.s3_key)
    except Exception as e:
        s3_error = str(e)
        logger.error(f"Failed to delete S3 object for export {export_id}: {e}")

    # Update status to expired regardless of S3 result
    # (if S3 delete fails, we still mark as expired to prevent repeated attempts)
    update_export_status(export_id, STATUS_EXPIRED)

    logger.info(f"Export expired: id={export_id}, s3_key={export.s3_key}, s3_deleted={s3_deleted}")

    # Emit audit event (non-blocking)
    try:
        audit = _get_audit_module()
        audit.log_export_expired(
            export_id=export_id,
            org_id=export.org_id,
            s3_deleted=s3_deleted,
            s3_error=s3_error,
        )
    except Exception as e:
        logger.warning(f"Failed to log export_expired audit event: {e}")

    return {
        "export_id": export_id,
        "success": True,
        "s3_key": export.s3_key,
        "s3_deleted": s3_deleted,
        "s3_error": s3_error,
    }


def run_expiration_job(limit: int = 100, dry_run: bool = False) -> dict:
    """
    Run the export expiration job.

    This is the main entry point for lifecycle enforcement.
    Call this from a cron job, management command, or admin endpoint.

    EXECUTION MODEL:
    - Manual or scheduled execution only
    - NO polling loops
    - NO background timers
    - Idempotent and safe to run multiple times

    Args:
        limit: Maximum number of exports to process in one run
        dry_run: If True, only report what would be expired without making changes

    Returns:
        dict with job results
    """
    started_at = datetime.utcnow().isoformat()
    logger.info(f"Starting export expiration job: limit={limit}, dry_run={dry_run}")

    # Get expired exports
    expired_exports = get_expired_exports(limit=limit)

    if dry_run:
        logger.info(f"Dry run: would expire {len(expired_exports)} exports")
        return {
            "started_at": started_at,
            "completed_at": datetime.utcnow().isoformat(),
            "dry_run": True,
            "total_found": len(expired_exports),
            "would_expire": [e.to_dict() for e in expired_exports],
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
        }

    # Process each export
    results = []
    succeeded = 0
    failed = 0

    for export in expired_exports:
        try:
            result = expire_export(export.id)
            results.append(result)
            if result["success"]:
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Unexpected error expiring export {export.id}: {e}")
            results.append({
                "export_id": export.id,
                "success": False,
                "error": str(e),
            })
            failed += 1

    completed_at = datetime.utcnow().isoformat()
    logger.info(f"Export expiration job completed: processed={len(expired_exports)}, succeeded={succeeded}, failed={failed}")

    return {
        "started_at": started_at,
        "completed_at": completed_at,
        "dry_run": False,
        "total_found": len(expired_exports),
        "processed": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


# =============================================================================
# EVIDENCE CHAIN (PROVENANCE) OPERATIONS
# =============================================================================

class ExportEvidenceLink:
    """Represents a link between an export and its source evidence."""

    def __init__(
        self,
        id: str,
        export_id: str,
        evidence_id: str,
        evidence_type: str,
        linked_at: str,
        linked_by: str,
    ):
        self.id = id
        self.export_id = export_id
        self.evidence_id = evidence_id
        self.evidence_type = evidence_type
        self.linked_at = linked_at
        self.linked_by = linked_by

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "export_id": self.export_id,
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "linked_at": self.linked_at,
            "linked_by": self.linked_by,
        }


def link_export_to_evidence(
    export_id: str,
    evidence_ids: list[str],
    evidence_type: str,
    user_id: str,
    request_id: Optional[str] = None,
) -> list[ExportEvidenceLink]:
    """
    Link an export to one or more evidence records.

    INSERT-ONLY: This function only inserts new links, never updates or deletes.

    Args:
        export_id: The export ID
        evidence_ids: List of evidence IDs to link
        evidence_type: Type of evidence (e.g., "evidence_refs", "audit_events")
        user_id: User ID who is creating the links
        request_id: Request ID for audit tracing (optional)

    Returns:
        List of created ExportEvidenceLink records

    Raises:
        ValueError: If export_id or evidence_ids is empty
    """
    if not export_id:
        raise ValueError("export_id is required")
    if not evidence_ids:
        raise ValueError("evidence_ids list cannot be empty")

    links = []
    now = datetime.utcnow().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        for evidence_id in evidence_ids:
            link_id = f"evl_{uuid4().hex[:16]}"

            conn.execute(
                """
                INSERT INTO export_evidence_links (id, export_id, evidence_id, evidence_type, linked_at, linked_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (link_id, export_id, evidence_id, evidence_type, now, user_id),
            )

            links.append(ExportEvidenceLink(
                id=link_id,
                export_id=export_id,
                evidence_id=evidence_id,
                evidence_type=evidence_type,
                linked_at=now,
                linked_by=user_id,
            ))

        conn.commit()

    logger.info(f"Linked export {export_id} to {len(links)} evidence records (type={evidence_type})")

    # Emit audit event for provenance linking (non-blocking)
    try:
        audit = _get_audit_module()
        audit.log_export_provenance_linked(
            export_id=export_id,
            evidence_ids=evidence_ids,
            evidence_type=evidence_type,
            user_id=user_id,
            request_id=request_id,
        )
    except Exception as e:
        logger.warning(f"Failed to log export_provenance_linked audit event: {e}")

    return links


def get_export_provenance(export_id: str) -> list[ExportEvidenceLink]:
    """
    Get all evidence links for an export.

    Args:
        export_id: The export ID

    Returns:
        List of ExportEvidenceLink records
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, export_id, evidence_id, evidence_type, linked_at, linked_by
            FROM export_evidence_links
            WHERE export_id = ?
            ORDER BY linked_at ASC
            """,
            (export_id,),
        )
        rows = cursor.fetchall()

    return [ExportEvidenceLink(**dict(row)) for row in rows]


def get_exports_for_evidence(evidence_id: str) -> list[ExportEvidenceLink]:
    """
    Get all exports linked to a specific evidence record.

    Useful for tracing which exports contain a specific piece of evidence.

    Args:
        evidence_id: The evidence ID

    Returns:
        List of ExportEvidenceLink records
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, export_id, evidence_id, evidence_type, linked_at, linked_by
            FROM export_evidence_links
            WHERE evidence_id = ?
            ORDER BY linked_at ASC
            """,
            (evidence_id,),
        )
        rows = cursor.fetchall()

    return [ExportEvidenceLink(**dict(row)) for row in rows]


def create_and_upload_export_with_provenance(
    data: bytes,
    org_id: str,
    user_id: str,
    filename: str,
    evidence_ids: list[str],
    evidence_type: str,
    content_type: str = "application/octet-stream",
    request_id: Optional[str] = None,
    retention_days: Optional[int] = None,
) -> Tuple[S3ExportRecord, list[ExportEvidenceLink]]:
    """
    Create a complete export with provenance: upload to S3, create DB record, link evidence, and emit audit events.

    This is the recommended entry point for backend export generation flows
    that need to track provenance to source evidence.

    Args:
        data: File content as bytes
        org_id: Organization ID
        user_id: User ID who created the export
        filename: Original filename
        evidence_ids: List of evidence IDs that this export is based on
        evidence_type: Type of evidence (e.g., "evidence_refs", "audit_events")
        content_type: MIME type of the file
        request_id: Request ID for audit tracing (optional)
        retention_days: Custom retention period (optional, defaults to DEFAULT_RETENTION_DAYS)

    Returns:
        Tuple of (S3ExportRecord, list of ExportEvidenceLink)

    Raises:
        ClientError: If S3 upload fails
        NoCredentialsError: If AWS credentials are not configured
        ValueError: If evidence_ids is empty
    """
    # Create and upload the export
    export = create_and_upload_export(
        data=data,
        org_id=org_id,
        user_id=user_id,
        filename=filename,
        content_type=content_type,
        request_id=request_id,
        retention_days=retention_days,
    )

    # Link to evidence
    links = link_export_to_evidence(
        export_id=export.id,
        evidence_ids=evidence_ids,
        evidence_type=evidence_type,
        user_id=user_id,
        request_id=request_id,
    )

    logger.info(f"Export created with provenance: id={export.id}, evidence_count={len(links)}")

    return export, links

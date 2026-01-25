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

# =============================================================================
# CONFIGURATION
# =============================================================================

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_EXPORTS_BUCKET = os.getenv("S3_EXPORTS_BUCKET", "reconai-prod-private-exports")

# Default URL expiration in seconds
DEFAULT_URL_EXPIRATION_SECONDS = 300


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
# S3 OPERATIONS
# =============================================================================

def generate_download_url(key: str, expires_seconds: int = DEFAULT_URL_EXPIRATION_SECONDS) -> str:
    """
    Generate a presigned download URL for a private S3 object.

    Args:
        key: The S3 object key (path within bucket)
        expires_seconds: URL expiration time in seconds (default: 300)

    Returns:
        Presigned URL string

    Raises:
        ClientError: If S3 operation fails
        NoCredentialsError: If AWS credentials are not configured
    """
    s3 = _get_s3_client()

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_EXPORTS_BUCKET,
            "Key": key,
        },
        ExpiresIn=expires_seconds,
    )

    logger.info(f"Generated presigned URL for key={key}, expires_in={expires_seconds}s")
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


def delete_export(key: str) -> bool:
    """
    Delete an export from S3.

    Args:
        key: The S3 object key

    Returns:
        True if deleted successfully

    Raises:
        ClientError: If S3 operation fails
    """
    s3 = _get_s3_client()

    s3.delete_object(
        Bucket=S3_EXPORTS_BUCKET,
        Key=key,
    )

    logger.info(f"Deleted export from S3: key={key}")
    return True


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

# app/services/document_service.py
"""
Document Service - First-Class Document Entity Management

This service implements:
- Document as System of Record (created BEFORE analysis)
- Strict lifecycle state machine
- Immutable audit trail
- Separation from bank data (document_transactions only)

LIFECYCLE STATES:
    uploaded -> validated -> processing -> completed
                    |            |
                    v            v
                 failed       failed

All state transitions are explicit and audited.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.db import DB_PATH

logger = logging.getLogger(__name__)


class DocumentStatus(str, Enum):
    """Document lifecycle states - explicit, no skipping."""
    UPLOADED = "uploaded"
    VALIDATED = "validated"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentSource(str, Enum):
    """Document origin - tracks data provenance."""
    UPLOAD = "upload"
    RECEIPT = "receipt"
    API = "api"
    MIGRATION = "migration"


class DocumentAuditAction(str, Enum):
    """Audit event types for documents."""
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_VALIDATED = "document_validated"
    DOCUMENT_PROCESSING_STARTED = "document_processing_started"
    DOCUMENT_COMPLETED = "document_completed"
    DOCUMENT_FAILED = "document_failed"
    DOCUMENT_TRANSACTION_CREATED = "document_transaction_created"


# Valid state transitions - enforced strictly
VALID_TRANSITIONS: Dict[DocumentStatus, List[DocumentStatus]] = {
    DocumentStatus.UPLOADED: [DocumentStatus.VALIDATED, DocumentStatus.FAILED],
    DocumentStatus.VALIDATED: [DocumentStatus.PROCESSING, DocumentStatus.FAILED],
    DocumentStatus.PROCESSING: [DocumentStatus.COMPLETED, DocumentStatus.FAILED],
    DocumentStatus.COMPLETED: [],  # Terminal state
    DocumentStatus.FAILED: [],  # Terminal state
}


def init_document_tables() -> None:
    """
    Initialize document pipeline tables.

    Tables:
    - documents: First-class document records
    - document_audit_log: Immutable audit trail
    - document_transactions: Derived transaction data (NOT bank data)
    """
    with sqlite3.connect(DB_PATH) as conn:
        # =================================================================
        # DOCUMENTS TABLE - System of Record
        # =================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL,

                -- Identity
                filename TEXT NOT NULL,
                content_type TEXT,
                file_size_bytes INTEGER,
                stored_path TEXT,

                -- Source tracking
                source TEXT NOT NULL DEFAULT 'upload',
                source_endpoint TEXT,

                -- Lifecycle
                status TEXT NOT NULL DEFAULT 'uploaded',
                failure_reason TEXT,

                -- Timestamps
                created_at TEXT DEFAULT (datetime('now')),
                validated_at TEXT,
                processing_started_at TEXT,
                completed_at TEXT,
                failed_at TEXT,
                updated_at TEXT DEFAULT (datetime('now')),

                -- Foreign keys
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)

        # Indexes for documents
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at)")

        # =================================================================
        # DOCUMENT AUDIT LOG - Immutable, Append-Only
        # =================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_audit_log (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,

                -- Audit info
                action TEXT NOT NULL,
                actor_id TEXT NOT NULL,

                -- State tracking
                old_status TEXT,
                new_status TEXT,

                -- Details
                details TEXT NOT NULL DEFAULT '{}',
                failure_reason TEXT,

                -- Metadata
                ip_address TEXT,
                user_agent TEXT,

                -- Timestamp (immutable)
                created_at TEXT DEFAULT (datetime('now')),

                -- Foreign keys
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)

        # Indexes for audit log
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_doc ON document_audit_log(document_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_org ON document_audit_log(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_action ON document_audit_log(action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_created ON document_audit_log(created_at)")

        # =================================================================
        # DOCUMENT TRANSACTIONS - Derived Data (NOT Bank Data)
        # =================================================================
        # This table is SEPARATE from bank transactions.
        # Provenance column ensures data lineage is always clear.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_transactions (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL,

                -- Transaction data
                tx_date TEXT,
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                merchant TEXT,

                -- Classification
                original_category TEXT,
                classification TEXT,
                reason TEXT,

                -- Provenance (REQUIRED - always track origin)
                provenance TEXT NOT NULL DEFAULT 'document_upload',

                -- Timestamps
                created_at TEXT DEFAULT (datetime('now')),

                -- Foreign keys
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)

        # Indexes for document transactions
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_tx_doc ON document_transactions(document_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_tx_org ON document_transactions(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_tx_user ON document_transactions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_tx_date ON document_transactions(tx_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_tx_provenance ON document_transactions(provenance)")

        conn.commit()
        logger.info("Document pipeline tables initialized")


class DocumentService:
    """
    Production document service with:
    - Document-first record creation
    - Explicit state machine
    - Immutable audit logging
    - Strict data lane separation
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_id(self) -> str:
        """Generate a unique document ID."""
        return f"doc_{uuid4().hex}"

    def _log_audit(
        self,
        conn: sqlite3.Connection,
        document_id: str,
        organization_id: str,
        action: DocumentAuditAction,
        actor_id: str,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        failure_reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Write an immutable audit log entry.

        This is APPEND-ONLY - no updates or deletes permitted.
        """
        audit_id = f"daud_{uuid4().hex}"
        conn.execute(
            """
            INSERT INTO document_audit_log
                (id, document_id, organization_id, action, actor_id,
                 old_status, new_status, details, failure_reason,
                 ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                document_id,
                organization_id,
                action.value,
                actor_id,
                old_status,
                new_status,
                json.dumps(details or {}),
                failure_reason,
                ip_address,
                user_agent,
            ),
        )
        logger.info(
            f"Document audit: action={action.value} doc={document_id} "
            f"org={organization_id} status={old_status}->{new_status}"
        )

    def _validate_transition(
        self,
        current_status: DocumentStatus,
        new_status: DocumentStatus,
    ) -> bool:
        """
        Validate state transition is allowed.

        Returns True if transition is valid, False otherwise.
        No skipping states is enforced here.
        """
        valid_next = VALID_TRANSITIONS.get(current_status, [])
        return new_status in valid_next

    # =========================================================================
    # DOCUMENT CREATION (BEFORE ANALYSIS)
    # =========================================================================

    def create_document(
        self,
        organization_id: str,
        user_id: str,
        filename: str,
        content_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        stored_path: Optional[str] = None,
        source: DocumentSource = DocumentSource.UPLOAD,
        source_endpoint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a document record BEFORE any analysis.

        This is the FIRST step in the document pipeline.
        The document exists immediately, regardless of what happens next.

        Args:
            organization_id: Organization owning the document
            user_id: User who uploaded the document
            filename: Original filename
            content_type: MIME type
            file_size_bytes: File size in bytes
            stored_path: Path where file is stored
            source: Document source (upload, receipt, api, migration)
            source_endpoint: The endpoint that received the upload
            ip_address: Client IP for audit
            user_agent: Client user agent for audit

        Returns:
            Dict with document_id and metadata
        """
        document_id = self._generate_id()

        with self._get_conn() as conn:
            # Create document record with status=uploaded
            conn.execute(
                """
                INSERT INTO documents
                    (id, organization_id, user_id, filename, content_type,
                     file_size_bytes, stored_path, source, source_endpoint,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    document_id,
                    organization_id,
                    user_id,
                    filename,
                    content_type,
                    file_size_bytes,
                    stored_path,
                    source.value,
                    source_endpoint,
                    DocumentStatus.UPLOADED.value,
                ),
            )

            # Audit: document_uploaded
            self._log_audit(
                conn=conn,
                document_id=document_id,
                organization_id=organization_id,
                action=DocumentAuditAction.DOCUMENT_UPLOADED,
                actor_id=user_id,
                old_status=None,
                new_status=DocumentStatus.UPLOADED.value,
                details={
                    "filename": filename,
                    "content_type": content_type,
                    "file_size_bytes": file_size_bytes,
                    "source": source.value,
                    "source_endpoint": source_endpoint,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            conn.commit()

        logger.info(
            f"Document created: id={document_id} org={organization_id} "
            f"filename={filename} source={source.value}"
        )

        return {
            "document_id": document_id,
            "organization_id": organization_id,
            "user_id": user_id,
            "filename": filename,
            "status": DocumentStatus.UPLOADED.value,
            "created_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # STATE TRANSITIONS
    # =========================================================================

    def mark_validated(
        self,
        document_id: str,
        actor_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Transition document: uploaded -> validated

        Called after file validation passes (type, size, security checks).
        """
        return self._transition_status(
            document_id=document_id,
            actor_id=actor_id,
            new_status=DocumentStatus.VALIDATED,
            audit_action=DocumentAuditAction.DOCUMENT_VALIDATED,
            timestamp_field="validated_at",
            details=details,
            ip_address=ip_address,
        )

    def mark_processing(
        self,
        document_id: str,
        actor_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Transition document: validated -> processing

        Called when analysis/parsing begins.
        """
        return self._transition_status(
            document_id=document_id,
            actor_id=actor_id,
            new_status=DocumentStatus.PROCESSING,
            audit_action=DocumentAuditAction.DOCUMENT_PROCESSING_STARTED,
            timestamp_field="processing_started_at",
            details=details,
            ip_address=ip_address,
        )

    def mark_completed(
        self,
        document_id: str,
        actor_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Transition document: processing -> completed

        Called when analysis completes successfully.
        """
        return self._transition_status(
            document_id=document_id,
            actor_id=actor_id,
            new_status=DocumentStatus.COMPLETED,
            audit_action=DocumentAuditAction.DOCUMENT_COMPLETED,
            timestamp_field="completed_at",
            details=details,
            ip_address=ip_address,
        )

    def mark_failed(
        self,
        document_id: str,
        actor_id: str,
        failure_reason: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Transition document: any -> failed

        Called when any step fails. Failure reason is REQUIRED.
        """
        return self._transition_status(
            document_id=document_id,
            actor_id=actor_id,
            new_status=DocumentStatus.FAILED,
            audit_action=DocumentAuditAction.DOCUMENT_FAILED,
            timestamp_field="failed_at",
            failure_reason=failure_reason,
            details=details,
            ip_address=ip_address,
        )

    def _transition_status(
        self,
        document_id: str,
        actor_id: str,
        new_status: DocumentStatus,
        audit_action: DocumentAuditAction,
        timestamp_field: str,
        failure_reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Generic state transition with validation and audit.

        Returns True if transition succeeded, False if invalid.
        """
        with self._get_conn() as conn:
            # Get current document
            row = conn.execute(
                "SELECT status, organization_id FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()

            if not row:
                logger.error(f"Document not found: {document_id}")
                return False

            current_status = DocumentStatus(row["status"])
            organization_id = row["organization_id"]

            # Validate transition (unless going to failed - always allowed)
            if new_status != DocumentStatus.FAILED:
                if not self._validate_transition(current_status, new_status):
                    logger.error(
                        f"Invalid transition: {current_status.value} -> {new_status.value} "
                        f"for document {document_id}"
                    )
                    return False

            # Update document
            conn.execute(
                f"""
                UPDATE documents
                SET status = ?,
                    failure_reason = ?,
                    {timestamp_field} = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_status.value, failure_reason, document_id),
            )

            # Audit
            self._log_audit(
                conn=conn,
                document_id=document_id,
                organization_id=organization_id,
                action=audit_action,
                actor_id=actor_id,
                old_status=current_status.value,
                new_status=new_status.value,
                details=details,
                failure_reason=failure_reason,
                ip_address=ip_address,
            )

            conn.commit()

        logger.info(
            f"Document transition: {document_id} {current_status.value} -> {new_status.value}"
        )
        return True

    # =========================================================================
    # DOCUMENT TRANSACTIONS (Derived Data - NOT Bank Data)
    # =========================================================================

    def create_document_transactions(
        self,
        document_id: str,
        organization_id: str,
        user_id: str,
        transactions: List[Dict[str, Any]],
        provenance: str = "document_upload",
        actor_id: Optional[str] = None,
    ) -> int:
        """
        Store transactions derived from a document.

        These go into document_transactions table ONLY.
        NEVER mixed with bank transactions.

        Args:
            document_id: Source document ID
            organization_id: Organization ID
            user_id: User ID
            transactions: List of transaction dicts
            provenance: Data origin marker (REQUIRED)
            actor_id: Actor for audit (defaults to user_id)

        Returns:
            Number of transactions created
        """
        if not transactions:
            return 0

        actor_id = actor_id or user_id
        count = 0

        with self._get_conn() as conn:
            for tx in transactions:
                tx_id = f"dtx_{uuid4().hex}"
                conn.execute(
                    """
                    INSERT INTO document_transactions
                        (id, document_id, organization_id, user_id,
                         tx_date, amount, description, merchant,
                         original_category, classification, reason,
                         provenance, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        tx_id,
                        document_id,
                        organization_id,
                        user_id,
                        tx.get("tx_date") or tx.get("date"),
                        tx.get("amount", 0),
                        tx.get("description", ""),
                        tx.get("merchant"),
                        tx.get("original_category"),
                        tx.get("classification"),
                        tx.get("reason"),
                        provenance,
                    ),
                )
                count += 1

            # Audit: document_transaction_created
            self._log_audit(
                conn=conn,
                document_id=document_id,
                organization_id=organization_id,
                action=DocumentAuditAction.DOCUMENT_TRANSACTION_CREATED,
                actor_id=actor_id,
                details={
                    "transaction_count": count,
                    "provenance": provenance,
                },
            )

            conn.commit()

        logger.info(
            f"Created {count} document transactions for doc={document_id} "
            f"provenance={provenance}"
        )
        return count

    # =========================================================================
    # QUERIES
    # =========================================================================

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get a document by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM documents WHERE id = ?
                """,
                (document_id,),
            ).fetchone()

            if row:
                return dict(row)
            return None

    def list_documents(
        self,
        organization_id: str,
        status: Optional[DocumentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List documents for an organization."""
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM documents
                    WHERE organization_id = ? AND status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (organization_id, status.value, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM documents
                    WHERE organization_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (organization_id, limit, offset),
                ).fetchall()

            return [dict(row) for row in rows]

    def get_document_audit_trail(
        self,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """Get full audit trail for a document."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM document_audit_log
                WHERE document_id = ?
                ORDER BY created_at ASC
                """,
                (document_id,),
            ).fetchall()

            return [dict(row) for row in rows]

    def get_document_transactions(
        self,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """Get transactions derived from a document."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM document_transactions
                WHERE document_id = ?
                ORDER BY tx_date DESC, created_at DESC
                """,
                (document_id,),
            ).fetchall()

            return [dict(row) for row in rows]


# Singleton instance
_document_service: Optional[DocumentService] = None


def get_document_service() -> DocumentService:
    """Get or create the global DocumentService instance."""
    global _document_service
    if _document_service is None:
        _document_service = DocumentService()
    return _document_service

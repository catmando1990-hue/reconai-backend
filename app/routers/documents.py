# app/routers/documents.py
"""
Document API Router

Provides visibility into the document pipeline:
- List documents with status filtering
- Get document details and audit trail
- Get document-derived transactions

No modifications allowed through this API - it's read-only visibility
into the document system of record.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth_context import AuthIdentity, get_current_identity
from app.services.document_service import (
    DocumentStatus,
    get_document_service,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _resolve_org_id(
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> str:
    """Resolve organization ID from header or user default."""
    if x_organization_id:
        return x_organization_id

    default_org_id = identity.get("default_org_id")
    if default_org_id:
        return default_org_id

    raise HTTPException(
        status_code=400,
        detail="Organization context required (set X-Organization-ID header)",
    )


@router.get("")
@router.get("/")
async def list_documents(
    status: Optional[str] = Query(None, description="Filter by status: uploaded, validated, processing, completed, failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: str = Depends(_resolve_org_id),
) -> Dict[str, Any]:
    """
    List all documents for the organization.

    Every upload produces a visible document record.
    Documents never disappear without a trace.
    """
    doc_service = get_document_service()

    # Validate status if provided
    status_filter = None
    if status:
        try:
            status_filter = DocumentStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid values: uploaded, validated, processing, completed, failed",
            )

    documents = doc_service.list_documents(
        organization_id=org_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    return {
        "organization_id": org_id,
        "documents": documents,
        "count": len(documents),
        "limit": limit,
        "offset": offset,
        "status_filter": status,
    }


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    org_id: str = Depends(_resolve_org_id),
) -> Dict[str, Any]:
    """
    Get a specific document by ID.

    Returns full document details including lifecycle state.
    """
    doc_service = get_document_service()

    document = doc_service.get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    # Verify org ownership
    if document.get("organization_id") != org_id:
        raise HTTPException(
            status_code=403,
            detail="Document does not belong to this organization",
        )

    return document


@router.get("/{document_id}/audit")
async def get_document_audit_trail(
    document_id: str,
    org_id: str = Depends(_resolve_org_id),
) -> Dict[str, Any]:
    """
    Get the full audit trail for a document.

    Returns all state transitions and actions, immutable and complete.
    No silent transitions - every change is recorded here.
    """
    doc_service = get_document_service()

    # First verify document exists and belongs to org
    document = doc_service.get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    if document.get("organization_id") != org_id:
        raise HTTPException(
            status_code=403,
            detail="Document does not belong to this organization",
        )

    audit_trail = doc_service.get_document_audit_trail(document_id)

    return {
        "document_id": document_id,
        "organization_id": org_id,
        "current_status": document.get("status"),
        "audit_trail": audit_trail,
        "event_count": len(audit_trail),
    }


@router.get("/{document_id}/transactions")
async def get_document_transactions(
    document_id: str,
    org_id: str = Depends(_resolve_org_id),
) -> Dict[str, Any]:
    """
    Get transactions derived from a document.

    These are document-derived transactions ONLY.
    Bank data is never mixed with document data.
    Provenance is always tracked.
    """
    doc_service = get_document_service()

    # First verify document exists and belongs to org
    document = doc_service.get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    if document.get("organization_id") != org_id:
        raise HTTPException(
            status_code=403,
            detail="Document does not belong to this organization",
        )

    transactions = doc_service.get_document_transactions(document_id)

    return {
        "document_id": document_id,
        "organization_id": org_id,
        "document_status": document.get("status"),
        "transactions": transactions,
        "count": len(transactions),
        "provenance": "document_upload",  # Always tracked
    }


@router.get("/stats/summary")
async def get_documents_summary(
    org_id: str = Depends(_resolve_org_id),
) -> Dict[str, Any]:
    """
    Get summary statistics for documents in the organization.

    Provides visibility into:
    - Total documents
    - Documents by status
    - Failed documents (with visibility into failures)
    """
    doc_service = get_document_service()

    # Get counts by status
    all_docs = doc_service.list_documents(organization_id=org_id, limit=1000)

    status_counts = {
        "uploaded": 0,
        "validated": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
    }

    for doc in all_docs:
        status = doc.get("status", "unknown")
        if status in status_counts:
            status_counts[status] += 1

    # Get recent failures for visibility
    failed_docs = doc_service.list_documents(
        organization_id=org_id,
        status=DocumentStatus.FAILED,
        limit=10,
    )

    recent_failures = [
        {
            "document_id": doc.get("id"),
            "filename": doc.get("filename"),
            "failure_reason": doc.get("failure_reason"),
            "failed_at": doc.get("failed_at"),
        }
        for doc in failed_docs
    ]

    return {
        "organization_id": org_id,
        "total_documents": len(all_docs),
        "by_status": status_counts,
        "recent_failures": recent_failures,
        "failure_count": status_counts["failed"],
    }

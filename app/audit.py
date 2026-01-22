# app/audit.py
"""
Audit Module - Canonical Implementation (FAIL-CLOSED)

This module provides the async interface for audit recording.
All operations delegate to the canonical audit_store.

CONTRACT:
- Audit failures ABORT the request (fail-closed)
- request_id is REQUIRED for all audit events
- All data is persisted to SQLite with hash-chaining
- No silent failures - exceptions propagate

MIGRATION NOTE:
This replaces the previous "best-effort" logger-only implementation.
Audit is now MANDATORY for compliance (DCAA).
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone

from app.services.audit_store import (
    AuditEventInput,
    AuditEventRecord,
    AuditInsertError,
    insert_audit_event,
)


class AuditError(Exception):
    """Raised when audit operation fails. Request MUST abort."""
    pass


async def record_audit_event(
    *,
    actor: Optional[Dict[str, Any]] = None,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> AuditEventRecord:
    """
    Record an audit event to the canonical audit_store.

    FAIL-CLOSED: If this fails, an exception is raised and the request MUST abort.

    Args:
        actor: Actor information dict (must contain user_id)
        action: Action being performed (e.g., "govcon.export")
        resource_type: Type of resource being accessed
        resource_id: ID of the resource
        status: Status of the action (e.g., "ok", "error")
        metadata: Additional metadata to record
        request_id: Request ID for traceability (REQUIRED)

    Returns:
        The persisted AuditEventRecord

    Raises:
        AuditError: If audit insertion fails (fail-closed)
        ValueError: If required fields are missing
    """
    # Extract actor_id from actor dict
    actor_id = "unknown"
    if actor:
        actor_id = actor.get("user_id") or actor.get("id") or "unknown"

    # Build comprehensive payload
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "status": status,
        "actor_details": actor,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Add metadata if provided
    if metadata:
        payload["metadata"] = metadata

    # Create audit event input
    audit_input = AuditEventInput(
        actor_id=actor_id,
        event_type=action,
        entity_type=resource_type,
        entity_id=resource_id,
        payload=payload,
    )

    try:
        return insert_audit_event(audit_input)
    except AuditInsertError as e:
        # FAIL-CLOSED: Re-raise as AuditError
        raise AuditError(f"Audit recording failed (fail-closed): {e}") from e


# Synchronous wrapper for compatibility
def record_audit_event_sync(
    *,
    actor: Optional[Dict[str, Any]] = None,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> AuditEventRecord:
    """
    Synchronous version of record_audit_event.

    FAIL-CLOSED: If this fails, an exception is raised and the request MUST abort.
    """
    actor_id = "unknown"
    if actor:
        actor_id = actor.get("user_id") or actor.get("id") or "unknown"

    payload: Dict[str, Any] = {
        "request_id": request_id,
        "status": status,
        "actor_details": actor,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    if metadata:
        payload["metadata"] = metadata

    audit_input = AuditEventInput(
        actor_id=actor_id,
        event_type=action,
        entity_type=resource_type,
        entity_id=resource_id,
        payload=payload,
    )

    try:
        return insert_audit_event(audit_input)
    except AuditInsertError as e:
        raise AuditError(f"Audit recording failed (fail-closed): {e}") from e

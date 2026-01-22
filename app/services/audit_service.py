# app/services/audit_service.py
"""
Audit Service - Compatibility Layer (FAIL-CLOSED)

IMPORTANT: This module is a COMPATIBILITY LAYER that delegates to the canonical
audit_store implementation. All audit operations MUST go through audit_store.

CONTRACT:
- All writes delegate to audit_store (persistent, hash-chained)
- Audit failures ABORT the request (fail-closed)
- request_id is REQUIRED for mutations
- No in-memory storage - all data persisted to SQLite

MIGRATION NOTE:
New code should import directly from app.services.audit_store.
This module exists for backward compatibility with existing code.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.audit_store import (
    AuditEventInput,
    AuditEventRecord,
    AuditInsertError,
    insert_audit_event,
    get_audit_events,
    count_audit_events,
)


class AuditServiceError(Exception):
    """Raised when audit service operation fails. MUST abort the request."""
    pass


class MissingRequestIdError(AuditServiceError):
    """Raised when request_id is missing from audit call."""
    pass


def record_audit(
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    payload: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> AuditEventRecord:
    """
    Record an audit entry via the canonical audit_store.

    FAIL-CLOSED: If this fails, an exception is raised and the request MUST abort.

    Args:
        actor: User ID performing the action
        action: Action type (e.g., "transaction_override", "maintenance_enabled")
        entity: Entity type (e.g., "transaction", "system")
        entity_id: Entity identifier
        payload: Additional data to record
        request_id: Request ID for traceability (REQUIRED - MANDATORY)

    Returns:
        The persisted AuditEventRecord

    Raises:
        MissingRequestIdError: If request_id is missing (MANDATORY)
        AuditServiceError: If audit insertion fails (fail-closed)
    """
    # MANDATORY: request_id is REQUIRED for all audit events
    if not request_id:
        raise MissingRequestIdError(
            f"request_id is REQUIRED for audit events (action={action}, entity={entity})"
        )

    # Build payload with request_id (ALWAYS present)
    audit_payload: Dict[str, Any] = payload.copy() if payload else {}
    audit_payload["request_id"] = request_id

    # Create audit event input
    audit_input = AuditEventInput(
        actor_id=actor,
        event_type=action,
        entity_type=entity,
        entity_id=entity_id,
        payload=audit_payload,
    )

    try:
        return insert_audit_event(audit_input)
    except AuditInsertError as e:
        # FAIL-CLOSED: Re-raise as AuditServiceError
        raise AuditServiceError(f"Audit recording failed (fail-closed): {e}") from e


def get_audit_entries(
    entity: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get audit entries from the canonical audit_store.

    Args:
        entity: Filter by entity type
        action: Filter by action/event type
        limit: Maximum entries to return

    Returns:
        List of audit entries as dicts (for backward compatibility)
    """
    records = get_audit_events(
        entity_type=entity,
        event_type=action,
        limit=limit,
    )

    # Convert to dict format for backward compatibility
    return [
        {
            "id": r.id,
            "actor": r.actor_id,
            "action": r.event_type,
            "entity": r.entity_type,
            "entity_id": r.entity_id,
            "payload": r.payload,
            "timestamp": r.created_at,
            "event_hash": r.event_hash,
        }
        for r in records
    ]


def get_audit_count(
    entity: Optional[str] = None,
    action: Optional[str] = None,
) -> int:
    """
    Get count of audit entries from the canonical audit_store.

    Args:
        entity: Filter by entity type
        action: Filter by action/event type

    Returns:
        Count of matching audit entries
    """
    return count_audit_events(
        entity_type=entity,
        event_type=action,
    )

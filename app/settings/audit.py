# app/settings/audit.py
"""
Settings Audit Module

Provides immutable audit records for all settings mutations.
Integrates with the canonical audit_store for DCAA-compliant persistence.

CONTRACT:
- previous_value: ALWAYS captured for mutations
- request_id: ALWAYS stored for traceability
- Append-only: No UPDATE or DELETE operations
- Fail-closed: Errors raise exceptions

EVENT TYPES:
- SETTINGS_NOTIFICATION_UPDATED
- SETTINGS_PROFILE_UPDATED
- SETTINGS_FINANCIAL_CONTROLS_UPDATED
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from app.services.audit_store import (
    AuditEventInput,
    AuditEventRecord,
    insert_audit_event,
    get_audit_events,
    AuditInsertError,
)


# =============================================================================
# SETTINGS AUDIT EVENT TYPES
# =============================================================================

SettingsAuditEventType = Literal[
    "SETTINGS_NOTIFICATION_UPDATED",
    "SETTINGS_PROFILE_UPDATED",
    "SETTINGS_FINANCIAL_CONTROLS_UPDATED",
    "SETTINGS_EXPORT_REQUESTED",
    "SETTINGS_ACCOUNT_DELETED",
]

VALID_SETTINGS_AUDIT_EVENT_TYPES = frozenset([
    "SETTINGS_NOTIFICATION_UPDATED",
    "SETTINGS_PROFILE_UPDATED",
    "SETTINGS_FINANCIAL_CONTROLS_UPDATED",
    "SETTINGS_EXPORT_REQUESTED",
    "SETTINGS_ACCOUNT_DELETED",
])


# =============================================================================
# SETTINGS AUDIT EVENT MODEL
# =============================================================================

@dataclass(frozen=True)
class SettingsAuditEvent:
    """
    Settings audit event for compliance tracking.

    CONTRACT:
    - request_id: ALWAYS present (for request traceability)
    - previous_value: ALWAYS present for mutations (None for create/delete)
    - new_value: ALWAYS present for mutations
    - actor_id: ALWAYS present (user who made the change)
    - entity_type: ALWAYS "settings"
    - entity_id: ALWAYS present (user_id or org_id)
    - event_type: ALWAYS one of VALID_SETTINGS_AUDIT_EVENT_TYPES
    """
    request_id: str
    actor_id: str
    event_type: SettingsAuditEventType
    entity_type: str  # "user_settings", "org_settings", "financial_controls"
    entity_id: str  # user_id or org_id
    previous_value: Optional[Dict[str, Any]]  # REQUIRED for mutations
    new_value: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


class SettingsAuditError(Exception):
    """Raised when settings audit operation fails."""
    pass


# =============================================================================
# AUDIT FUNCTIONS
# =============================================================================

def record_settings_audit(
    event: SettingsAuditEvent,
) -> AuditEventRecord:
    """
    Record a settings audit event to the immutable audit store.

    This function:
    1. Validates the event type
    2. Constructs the payload with previous_value and request_id
    3. Delegates to the canonical audit_store for persistence

    Args:
        event: The settings audit event to record

    Returns:
        The persisted audit event record

    Raises:
        SettingsAuditError: If validation fails or insertion fails
    """
    # Validate event type (fail-closed)
    if event.event_type not in VALID_SETTINGS_AUDIT_EVENT_TYPES:
        raise SettingsAuditError(
            f"Invalid settings audit event type: {event.event_type}. "
            f"Must be one of: {sorted(VALID_SETTINGS_AUDIT_EVENT_TYPES)}"
        )

    # Build payload with required fields
    payload: Dict[str, Any] = {
        "request_id": event.request_id,  # ALWAYS present
        "previous_value": event.previous_value,  # ALWAYS present (can be None)
        "new_value": event.new_value,
        "changed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Add optional metadata
    if event.metadata:
        payload["metadata"] = event.metadata

    # Create audit event input
    audit_input = AuditEventInput(
        actor_id=event.actor_id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        payload=payload,
    )

    try:
        return insert_audit_event(audit_input)
    except AuditInsertError as e:
        raise SettingsAuditError(f"Failed to record settings audit: {e}") from e


def get_settings_audit_trail(
    entity_type: str,
    entity_id: str,
    limit: int = 100,
) -> list[AuditEventRecord]:
    """
    Get the audit trail for a specific settings entity.

    Args:
        entity_type: The entity type (e.g., "user_settings", "org_settings")
        entity_id: The entity ID (user_id or org_id)
        limit: Maximum records to return

    Returns:
        List of audit events, ordered by created_at DESC
    """
    return get_audit_events(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )


# =============================================================================
# HELPER FUNCTIONS FOR COMMON AUDIT SCENARIOS
# =============================================================================

def audit_notification_settings_change(
    request_id: str,
    user_id: str,
    previous_settings: Dict[str, Any],
    new_settings: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventRecord:
    """
    Record an audit event for notification settings changes.

    Args:
        request_id: The request ID for traceability
        user_id: The user whose settings were changed
        previous_settings: The settings before the change
        new_settings: The settings after the change
        metadata: Optional additional metadata

    Returns:
        The persisted audit event record
    """
    event = SettingsAuditEvent(
        request_id=request_id,
        actor_id=user_id,
        event_type="SETTINGS_NOTIFICATION_UPDATED",
        entity_type="user_settings",
        entity_id=user_id,
        previous_value=previous_settings,
        new_value=new_settings,
        metadata=metadata,
    )
    return record_settings_audit(event)


def audit_profile_change(
    request_id: str,
    user_id: str,
    previous_profile: Dict[str, Any],
    new_profile: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventRecord:
    """
    Record an audit event for profile changes.

    Args:
        request_id: The request ID for traceability
        user_id: The user whose profile was changed
        previous_profile: The profile before the change
        new_profile: The profile after the change
        metadata: Optional additional metadata

    Returns:
        The persisted audit event record
    """
    event = SettingsAuditEvent(
        request_id=request_id,
        actor_id=user_id,
        event_type="SETTINGS_PROFILE_UPDATED",
        entity_type="user_settings",
        entity_id=user_id,
        previous_value=previous_profile,
        new_value=new_profile,
        metadata=metadata,
    )
    return record_settings_audit(event)


def audit_financial_controls_change(
    request_id: str,
    actor_id: str,
    org_id: str,
    previous_controls: Dict[str, Any],
    new_controls: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventRecord:
    """
    Record an audit event for financial controls changes.

    Args:
        request_id: The request ID for traceability
        actor_id: The user who made the change
        org_id: The organization whose controls were changed
        previous_controls: The controls before the change
        new_controls: The controls after the change
        metadata: Optional additional metadata

    Returns:
        The persisted audit event record
    """
    event = SettingsAuditEvent(
        request_id=request_id,
        actor_id=actor_id,
        event_type="SETTINGS_FINANCIAL_CONTROLS_UPDATED",
        entity_type="financial_controls",
        entity_id=org_id,
        previous_value=previous_controls,
        new_value=new_controls,
        metadata=metadata,
    )
    return record_settings_audit(event)


def audit_data_export(
    request_id: str,
    user_id: str,
    export_type: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventRecord:
    """
    Record an audit event for data export requests.

    Args:
        request_id: The request ID for traceability
        user_id: The user who requested the export
        export_type: Type of export (e.g., "full", "transactions", "audit")
        metadata: Optional additional metadata

    Returns:
        The persisted audit event record
    """
    event = SettingsAuditEvent(
        request_id=request_id,
        actor_id=user_id,
        event_type="SETTINGS_EXPORT_REQUESTED",
        entity_type="user_settings",
        entity_id=user_id,
        previous_value=None,
        new_value={"export_type": export_type},
        metadata=metadata,
    )
    return record_settings_audit(event)


def audit_account_deletion(
    request_id: str,
    user_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEventRecord:
    """
    Record an audit event for account deletion.

    Args:
        request_id: The request ID for traceability
        user_id: The user whose account was deleted
        metadata: Optional additional metadata

    Returns:
        The persisted audit event record
    """
    event = SettingsAuditEvent(
        request_id=request_id,
        actor_id=user_id,
        event_type="SETTINGS_ACCOUNT_DELETED",
        entity_type="user_settings",
        entity_id=user_id,
        previous_value=None,
        new_value={"deleted": True},
        metadata=metadata,
    )
    return record_settings_audit(event)

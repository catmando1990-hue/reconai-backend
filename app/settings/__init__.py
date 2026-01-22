# app/settings/__init__.py
"""
Settings Contract Module

Exports canonical contract versioning, validation utilities,
and audit functions for all settings-related API endpoints.
"""

from app.settings.contract import (
    SETTINGS_CONTRACT_VERSION,
    VALID_SETTINGS_LIFECYCLE_STATUSES,
    SettingsLifecycleStatus,
    SettingsLifecycle,
    SettingsMetadata,
    create_settings_lifecycle,
    create_settings_metadata,
    wrap_settings_response,
)

from app.settings.audit import (
    SettingsAuditEvent,
    SettingsAuditError,
    VALID_SETTINGS_AUDIT_EVENT_TYPES,
    record_settings_audit,
    get_settings_audit_trail,
    audit_notification_settings_change,
    audit_profile_change,
    audit_financial_controls_change,
    audit_data_export,
    audit_account_deletion,
)

__all__ = [
    # Contract
    "SETTINGS_CONTRACT_VERSION",
    "VALID_SETTINGS_LIFECYCLE_STATUSES",
    "SettingsLifecycleStatus",
    "SettingsLifecycle",
    "SettingsMetadata",
    "create_settings_lifecycle",
    "create_settings_metadata",
    "wrap_settings_response",
    # Audit
    "SettingsAuditEvent",
    "SettingsAuditError",
    "VALID_SETTINGS_AUDIT_EVENT_TYPES",
    "record_settings_audit",
    "get_settings_audit_trail",
    "audit_notification_settings_change",
    "audit_profile_change",
    "audit_financial_controls_change",
    "audit_data_export",
    "audit_account_deletion",
]

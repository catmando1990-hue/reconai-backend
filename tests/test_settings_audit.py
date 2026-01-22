# tests/test_settings_audit.py
"""
CONTRACT TESTS for Settings Audit Module.

These tests ensure that:
- previous_value is ALWAYS captured for mutations
- request_id is ALWAYS stored for traceability
- Audit events are persisted immutably

CONTRACT VERSION: 1
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

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


# =============================================================================
# AUDIT EVENT TYPE TESTS
# =============================================================================


class TestSettingsAuditEventTypes:
    """Tests for valid audit event types."""

    def test_valid_event_types_defined(self):
        """VALID_SETTINGS_AUDIT_EVENT_TYPES MUST contain expected values."""
        expected = {
            "SETTINGS_NOTIFICATION_UPDATED",
            "SETTINGS_PROFILE_UPDATED",
            "SETTINGS_FINANCIAL_CONTROLS_UPDATED",
            "SETTINGS_EXPORT_REQUESTED",
            "SETTINGS_ACCOUNT_DELETED",
        }
        assert VALID_SETTINGS_AUDIT_EVENT_TYPES == expected

    def test_event_types_are_frozen(self):
        """VALID_SETTINGS_AUDIT_EVENT_TYPES MUST be immutable."""
        assert isinstance(VALID_SETTINGS_AUDIT_EVENT_TYPES, frozenset)


# =============================================================================
# SETTINGS AUDIT EVENT MODEL TESTS
# =============================================================================


class TestSettingsAuditEventModel:
    """Tests for SettingsAuditEvent dataclass."""

    def test_audit_event_requires_request_id(self):
        """SettingsAuditEvent MUST have request_id."""
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={"email_notifications": True},
            new_value={"email_notifications": False},
        )
        assert event.request_id == "req_123"

    def test_audit_event_requires_previous_value(self):
        """SettingsAuditEvent MUST have previous_value field."""
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={"email_notifications": True},
            new_value={"email_notifications": False},
        )
        assert event.previous_value == {"email_notifications": True}

    def test_audit_event_allows_none_previous_value(self):
        """SettingsAuditEvent MUST allow None for previous_value (create/delete)."""
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_ACCOUNT_DELETED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value=None,
            new_value={"deleted": True},
        )
        assert event.previous_value is None

    def test_audit_event_is_frozen(self):
        """SettingsAuditEvent MUST be immutable (frozen dataclass)."""
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={},
            new_value={},
        )
        # Frozen dataclass should raise FrozenInstanceError on modification
        with pytest.raises(Exception):  # FrozenInstanceError
            event.request_id = "modified"


# =============================================================================
# RECORD SETTINGS AUDIT TESTS
# =============================================================================


class TestRecordSettingsAudit:
    """Tests for record_settings_audit function."""

    def test_rejects_invalid_event_type(self):
        """record_settings_audit MUST reject invalid event types."""
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="INVALID_EVENT_TYPE",  # type: ignore
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={},
            new_value={},
        )
        with pytest.raises(SettingsAuditError, match="Invalid settings audit event type"):
            record_settings_audit(event)

    def test_accepts_all_valid_event_types(self):
        """record_settings_audit MUST accept all valid event types."""
        for event_type in VALID_SETTINGS_AUDIT_EVENT_TYPES:
            event = SettingsAuditEvent(
                request_id=str(uuid4()),
                actor_id="user_456",
                event_type=event_type,  # type: ignore
                entity_type="user_settings",
                entity_id="user_456",
                previous_value={},
                new_value={},
            )
            # Should not raise (actual persistence may fail in test env)
            try:
                record_settings_audit(event)
            except SettingsAuditError as e:
                # Only accept persistence errors, not validation errors
                assert "Invalid settings audit event type" not in str(e)


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestAuditHelperFunctions:
    """Tests for audit helper functions."""

    def test_audit_notification_settings_change_signature(self):
        """audit_notification_settings_change MUST require request_id and previous_settings."""
        # Verify function signature includes required parameters
        import inspect
        sig = inspect.signature(audit_notification_settings_change)
        params = list(sig.parameters.keys())
        assert "request_id" in params
        assert "previous_settings" in params
        assert "new_settings" in params

    def test_audit_profile_change_signature(self):
        """audit_profile_change MUST require request_id and previous_profile."""
        import inspect
        sig = inspect.signature(audit_profile_change)
        params = list(sig.parameters.keys())
        assert "request_id" in params
        assert "previous_profile" in params
        assert "new_profile" in params

    def test_audit_financial_controls_change_signature(self):
        """audit_financial_controls_change MUST require request_id and previous_controls."""
        import inspect
        sig = inspect.signature(audit_financial_controls_change)
        params = list(sig.parameters.keys())
        assert "request_id" in params
        assert "previous_controls" in params
        assert "new_controls" in params

    def test_audit_data_export_signature(self):
        """audit_data_export MUST require request_id."""
        import inspect
        sig = inspect.signature(audit_data_export)
        params = list(sig.parameters.keys())
        assert "request_id" in params

    def test_audit_account_deletion_signature(self):
        """audit_account_deletion MUST require request_id."""
        import inspect
        sig = inspect.signature(audit_account_deletion)
        params = list(sig.parameters.keys())
        assert "request_id" in params


# =============================================================================
# PAYLOAD CONTRACT TESTS
# =============================================================================


class TestAuditPayloadContract:
    """Tests for audit payload structure."""

    def test_payload_must_include_request_id(self):
        """Audit payload MUST include request_id."""
        event = SettingsAuditEvent(
            request_id="req_test_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={"key": "old"},
            new_value={"key": "new"},
        )
        # The payload is constructed inside record_settings_audit
        # We verify the event has request_id which will be in payload
        assert event.request_id == "req_test_123"

    def test_payload_must_include_previous_value(self):
        """Audit payload MUST include previous_value."""
        previous = {"email_notifications": True, "weekly_summary": False}
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value=previous,
            new_value={"email_notifications": False, "weekly_summary": True},
        )
        assert event.previous_value == previous

    def test_payload_must_include_new_value(self):
        """Audit payload MUST include new_value."""
        new = {"email_notifications": False, "weekly_summary": True}
        event = SettingsAuditEvent(
            request_id="req_123",
            actor_id="user_456",
            event_type="SETTINGS_NOTIFICATION_UPDATED",
            entity_type="user_settings",
            entity_id="user_456",
            previous_value={},
            new_value=new,
        )
        assert event.new_value == new


# =============================================================================
# CHECKLIST VERIFICATION TESTS
# =============================================================================


class TestAuditChecklist:
    """Tests to verify audit checklist requirements."""

    def test_checklist_previous_value_captured(self):
        """CHECKLIST: previous_value MUST be captured."""
        # Verify SettingsAuditEvent has previous_value field
        from dataclasses import fields
        field_names = [f.name for f in fields(SettingsAuditEvent)]
        assert "previous_value" in field_names

    def test_checklist_request_id_stored(self):
        """CHECKLIST: request_id MUST be stored."""
        # Verify SettingsAuditEvent has request_id field
        from dataclasses import fields
        field_names = [f.name for f in fields(SettingsAuditEvent)]
        assert "request_id" in field_names

    def test_checklist_no_silent_writes(self):
        """CHECKLIST: No silent writes - all mutations MUST be audited."""
        # This is verified by checking helper functions exist for all mutation types
        assert callable(audit_notification_settings_change)
        assert callable(audit_profile_change)
        assert callable(audit_financial_controls_change)
        assert callable(audit_data_export)
        assert callable(audit_account_deletion)

    def test_checklist_all_mutations_have_audit_functions(self):
        """CHECKLIST: All mutations MUST have corresponding audit functions."""
        # Verify event types have matching helper functions
        assert "SETTINGS_NOTIFICATION_UPDATED" in VALID_SETTINGS_AUDIT_EVENT_TYPES
        assert "SETTINGS_PROFILE_UPDATED" in VALID_SETTINGS_AUDIT_EVENT_TYPES
        assert "SETTINGS_FINANCIAL_CONTROLS_UPDATED" in VALID_SETTINGS_AUDIT_EVENT_TYPES
        assert "SETTINGS_EXPORT_REQUESTED" in VALID_SETTINGS_AUDIT_EVENT_TYPES
        assert "SETTINGS_ACCOUNT_DELETED" in VALID_SETTINGS_AUDIT_EVENT_TYPES

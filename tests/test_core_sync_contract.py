# tests/test_core_sync_contract.py
"""
CONTRACT TESTS for CORE Sync Lifecycle.

These tests LOCK the backend contract for `/api/core/state.sync`.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

Required fields in `sync` object:
- sync_version: int (ALWAYS present)
- status: str (MUST be one of: never, running, success, failed)
- sync_started_at: Optional[str]
- last_completed_at: Optional[str]
- last_successful_at: Optional[str]
- error_reason: Optional[str]
- request_id: Optional[str]
"""

import pytest
from app.routers.core_state import (
    SyncLifecycleResponse,
    SyncStatusValidationError,
    SYNC_CONTRACT_VERSION,
    VALID_SYNC_STATUSES,
    validate_sync_status,
)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


class TestSyncContractVersion:
    """Tests for sync_version field presence and correctness."""

    def test_sync_version_is_integer(self):
        """sync_version MUST be an integer."""
        assert isinstance(SYNC_CONTRACT_VERSION, int)

    def test_sync_version_is_positive(self):
        """sync_version MUST be positive."""
        assert SYNC_CONTRACT_VERSION > 0

    def test_sync_version_current_value(self):
        """sync_version MUST be 1 (current contract version)."""
        assert SYNC_CONTRACT_VERSION == 1

    def test_sync_version_always_present_in_response(self):
        """sync_version MUST always be present in SyncLifecycleResponse."""
        response = SyncLifecycleResponse.create_validated(status="never")
        assert hasattr(response, "sync_version")
        assert response.sync_version == SYNC_CONTRACT_VERSION

    def test_sync_version_present_for_all_valid_statuses(self):
        """sync_version MUST be present for all valid status values."""
        for status in VALID_SYNC_STATUSES:
            response = SyncLifecycleResponse.create_validated(status=status)
            assert response.sync_version == SYNC_CONTRACT_VERSION, (
                f"sync_version missing or incorrect for status '{status}'"
            )


# =============================================================================
# STATUS ENUM VALIDATION TESTS
# =============================================================================


class TestSyncStatusEnum:
    """Tests for strict status enum validation."""

    def test_valid_statuses_are_exhaustive(self):
        """VALID_SYNC_STATUSES MUST contain exactly the documented values."""
        expected = {"never", "running", "success", "failed"}
        assert VALID_SYNC_STATUSES == expected

    def test_valid_statuses_is_frozen(self):
        """VALID_SYNC_STATUSES MUST be immutable (frozenset)."""
        assert isinstance(VALID_SYNC_STATUSES, frozenset)

    @pytest.mark.parametrize("status", ["never", "running", "success", "failed"])
    def test_valid_status_accepted(self, status: str):
        """Valid status values MUST be accepted."""
        result = validate_sync_status(status)
        assert result == status

    @pytest.mark.parametrize("invalid_status", [
        "NEVER",  # Case sensitive
        "Running",  # Case sensitive
        "SUCCESS",  # Case sensitive
        "FAILED",  # Case sensitive
        "pending",  # Not in enum
        "syncing",  # Legacy value, not allowed
        "idle",  # Legacy value, not allowed
        "unknown",  # Invalid
        "",  # Empty string
        " ",  # Whitespace
        "never ",  # Trailing space
        " never",  # Leading space
    ])
    def test_invalid_status_rejected(self, invalid_status: str):
        """Invalid status values MUST be rejected with SyncStatusValidationError."""
        with pytest.raises(SyncStatusValidationError):
            validate_sync_status(invalid_status)

    def test_invalid_status_error_message_is_explicit(self):
        """Error message MUST list valid statuses."""
        with pytest.raises(SyncStatusValidationError) as exc_info:
            validate_sync_status("invalid")

        error_msg = str(exc_info.value)
        assert "invalid" in error_msg.lower()
        assert "never" in error_msg or "failed" in error_msg  # Lists valid values


# =============================================================================
# SYNC LIFECYCLE RESPONSE SHAPE TESTS
# =============================================================================


class TestSyncLifecycleResponseShape:
    """Tests for the exact shape of SyncLifecycleResponse."""

    def test_required_fields_exist(self):
        """All required fields MUST exist in SyncLifecycleResponse."""
        required_fields = {
            "sync_version",
            "status",
            "sync_started_at",
            "last_completed_at",
            "last_successful_at",
            "error_reason",
            "request_id",
        }
        response = SyncLifecycleResponse.create_validated(status="never")
        actual_fields = set(response.model_dump().keys())

        missing = required_fields - actual_fields
        assert not missing, f"Missing required fields: {missing}"

    def test_no_extra_fields(self):
        """SyncLifecycleResponse MUST NOT have undocumented fields."""
        expected_fields = {
            "sync_version",
            "status",
            "sync_started_at",
            "last_completed_at",
            "last_successful_at",
            "error_reason",
            "request_id",
        }
        response = SyncLifecycleResponse.create_validated(status="never")
        actual_fields = set(response.model_dump().keys())

        extra = actual_fields - expected_fields
        assert not extra, f"Unexpected fields: {extra}"

    def test_field_types(self):
        """Field types MUST match the contract."""
        response = SyncLifecycleResponse.create_validated(
            status="running",
            sync_started_at="2024-01-01T00:00:00",
            last_completed_at="2024-01-01T00:00:00",
            last_successful_at="2024-01-01T00:00:00",
            error_reason="test error",
            request_id="test_request_123",
        )
        data = response.model_dump()

        assert isinstance(data["sync_version"], int)
        assert isinstance(data["status"], str)
        assert isinstance(data["sync_started_at"], str)
        assert isinstance(data["last_completed_at"], str)
        assert isinstance(data["last_successful_at"], str)
        assert isinstance(data["error_reason"], str)
        assert isinstance(data["request_id"], str)

    def test_optional_fields_can_be_null(self):
        """Optional fields MUST allow None values."""
        response = SyncLifecycleResponse.create_validated(status="never")
        data = response.model_dump()

        # These fields are optional and should be None
        assert data["sync_started_at"] is None
        assert data["last_completed_at"] is None
        assert data["last_successful_at"] is None
        assert data["error_reason"] is None
        assert data["request_id"] is None


# =============================================================================
# CREATE_VALIDATED FACTORY TESTS
# =============================================================================


class TestCreateValidatedFactory:
    """Tests for SyncLifecycleResponse.create_validated factory method."""

    def test_create_validated_returns_correct_type(self):
        """create_validated MUST return SyncLifecycleResponse."""
        result = SyncLifecycleResponse.create_validated(status="never")
        assert isinstance(result, SyncLifecycleResponse)

    def test_create_validated_sets_sync_version(self):
        """create_validated MUST set sync_version to SYNC_CONTRACT_VERSION."""
        result = SyncLifecycleResponse.create_validated(status="never")
        assert result.sync_version == SYNC_CONTRACT_VERSION

    def test_create_validated_rejects_invalid_status(self):
        """create_validated MUST reject invalid status values."""
        with pytest.raises(SyncStatusValidationError):
            SyncLifecycleResponse.create_validated(status="invalid")

    def test_create_validated_preserves_all_fields(self):
        """create_validated MUST preserve all provided field values."""
        result = SyncLifecycleResponse.create_validated(
            status="failed",
            sync_started_at="2024-01-01T00:00:00",
            last_completed_at="2024-01-01T01:00:00",
            last_successful_at="2024-01-01T00:30:00",
            error_reason="Connection timeout",
            request_id="req_abc123",
        )

        assert result.status == "failed"
        assert result.sync_started_at == "2024-01-01T00:00:00"
        assert result.last_completed_at == "2024-01-01T01:00:00"
        assert result.last_successful_at == "2024-01-01T00:30:00"
        assert result.error_reason == "Connection timeout"
        assert result.request_id == "req_abc123"


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestDeterministicBehavior:
    """Tests to ensure deterministic behavior (no randomness in contract)."""

    def test_same_input_produces_same_output(self):
        """Same inputs MUST produce identical outputs."""
        result1 = SyncLifecycleResponse.create_validated(
            status="success",
            sync_started_at="2024-01-01T00:00:00",
            request_id="req_123",
        )
        result2 = SyncLifecycleResponse.create_validated(
            status="success",
            sync_started_at="2024-01-01T00:00:00",
            request_id="req_123",
        )

        assert result1.model_dump() == result2.model_dump()

    def test_sync_version_is_stable(self):
        """sync_version MUST be stable across multiple calls."""
        versions = [
            SyncLifecycleResponse.create_validated(status="never").sync_version
            for _ in range(10)
        ]
        assert all(v == SYNC_CONTRACT_VERSION for v in versions)

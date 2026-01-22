# tests/test_settings_contract.py
"""
CONTRACT TESTS for Settings API.

These tests LOCK the backend contract for Settings endpoints.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

All Settings responses MUST include:
- settings_version: int (ALWAYS present, value = 1)
- lifecycle: dict (ALWAYS present, status + reason_code)
- metadata: dict (ALWAYS present, sources, scope, timestamps)
"""

import pytest
from app.settings.contract import (
    SETTINGS_CONTRACT_VERSION,
    VALID_SETTINGS_LIFECYCLE_STATUSES,
    create_settings_lifecycle,
    create_settings_metadata,
    wrap_settings_response,
    SettingsLifecycle,
    SettingsMetadata,
)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


class TestSettingsContractVersion:
    """Tests for SETTINGS_CONTRACT_VERSION constant."""

    def test_settings_version_is_integer(self):
        """SETTINGS_CONTRACT_VERSION MUST be an integer."""
        assert isinstance(SETTINGS_CONTRACT_VERSION, int)

    def test_settings_version_is_positive(self):
        """SETTINGS_CONTRACT_VERSION MUST be positive."""
        assert SETTINGS_CONTRACT_VERSION > 0

    def test_settings_version_current_value(self):
        """SETTINGS_CONTRACT_VERSION MUST be 1 (current contract version)."""
        assert SETTINGS_CONTRACT_VERSION == 1


# =============================================================================
# LIFECYCLE VALIDATION TESTS
# =============================================================================


class TestSettingsLifecycleValidation:
    """Tests for lifecycle validation logic."""

    def test_lifecycle_valid_statuses(self):
        """VALID_SETTINGS_LIFECYCLE_STATUSES MUST contain expected values."""
        expected = {"success", "partial", "failed", "no_data"}
        assert VALID_SETTINGS_LIFECYCLE_STATUSES == expected

    def test_lifecycle_requires_reason_code_for_non_success(self):
        """reason_code MUST be present when status != success."""
        for status in ["partial", "failed", "no_data"]:
            with pytest.raises(ValueError, match="reason_code is required"):
                create_settings_lifecycle(status)

    def test_lifecycle_clears_reason_code_for_success(self):
        """reason_code MUST be None for success status."""
        lifecycle = create_settings_lifecycle("success", "SHOULD_BE_CLEARED")
        assert lifecycle["reason_code"] is None

    def test_lifecycle_rejects_invalid_status(self):
        """Invalid status values MUST be rejected."""
        with pytest.raises(ValueError, match="Invalid Settings lifecycle status"):
            create_settings_lifecycle("invalid_status")

    def test_lifecycle_accepts_all_valid_statuses(self):
        """All valid statuses MUST be accepted."""
        for status in ["success", "partial", "failed", "no_data"]:
            if status == "success":
                lifecycle = create_settings_lifecycle(status)
            else:
                lifecycle = create_settings_lifecycle(status, "TEST_REASON")
            assert lifecycle["status"] == status


# =============================================================================
# SETTINGS METADATA TESTS
# =============================================================================


class TestSettingsMetadata:
    """Tests for settings metadata validation logic."""

    def test_metadata_includes_sources(self):
        """Metadata MUST include sources list."""
        metadata = create_settings_metadata(["source1", "source2"])
        assert "sources" in metadata
        assert metadata["sources"] == ["source1", "source2"]

    def test_metadata_includes_scope(self):
        """Metadata MUST include scope."""
        metadata = create_settings_metadata(["source"], scope="user")
        assert "scope" in metadata
        assert metadata["scope"] == "user"

    def test_metadata_validates_scope(self):
        """Metadata MUST reject invalid scope values."""
        with pytest.raises(ValueError, match="Invalid settings scope"):
            create_settings_metadata(["source"], scope="invalid_scope")

    def test_metadata_accepts_all_valid_scopes(self):
        """Metadata MUST accept all valid scope values."""
        for scope in ["user", "organization", "system"]:
            metadata = create_settings_metadata(["source"], scope=scope)
            assert metadata["scope"] == scope

    def test_metadata_includes_last_modified_at(self):
        """Metadata MUST include last_modified_at timestamp."""
        metadata = create_settings_metadata(["source"])
        assert "last_modified_at" in metadata
        assert isinstance(metadata["last_modified_at"], str)

    def test_metadata_includes_modified_by(self):
        """Metadata MUST include modified_by field."""
        metadata = create_settings_metadata(["source"], modified_by="user_123")
        assert "modified_by" in metadata
        assert metadata["modified_by"] == "user_123"

    def test_metadata_allows_none_modified_by(self):
        """Metadata MUST allow None for modified_by."""
        metadata = create_settings_metadata(["source"])
        assert "modified_by" in metadata
        assert metadata["modified_by"] is None


# =============================================================================
# WRAP SETTINGS RESPONSE TESTS
# =============================================================================


class TestWrapSettingsResponse:
    """Tests for wrap_settings_response function."""

    def test_wrap_response_includes_version(self):
        """wrap_settings_response MUST return settings_version."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "settings_version" in response
        assert response["settings_version"] == SETTINGS_CONTRACT_VERSION

    def test_wrap_response_includes_lifecycle(self):
        """wrap_settings_response MUST return lifecycle."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "lifecycle" in response
        assert "status" in response["lifecycle"]
        assert response["lifecycle"]["status"] == "success"

    def test_wrap_response_includes_metadata(self):
        """wrap_settings_response MUST return metadata."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "metadata" in response
        assert "sources" in response["metadata"]
        assert "scope" in response["metadata"]
        assert "last_modified_at" in response["metadata"]
        assert "modified_by" in response["metadata"]

    def test_wrap_response_version_is_integer(self):
        """settings_version in wrap_settings_response MUST be integer."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert isinstance(response["settings_version"], int)

    def test_wrap_response_with_extra_fields_preserves_version(self):
        """Extra fields MUST not override settings_version."""
        response = wrap_settings_response(
            ok=True,
            sources=["test"],
            custom_field="value",
        )
        assert "settings_version" in response
        assert response["settings_version"] == SETTINGS_CONTRACT_VERSION
        assert response["custom_field"] == "value"

    def test_wrap_response_with_failed_lifecycle(self):
        """wrap_settings_response MUST handle failed lifecycle correctly."""
        response = wrap_settings_response(
            ok=False,
            sources=["test"],
            lifecycle_status="failed",
            lifecycle_reason="TEST_FAILURE",
        )
        assert response["lifecycle"]["status"] == "failed"
        assert response["lifecycle"]["reason_code"] == "TEST_FAILURE"

    def test_wrap_response_with_scope(self):
        """wrap_settings_response MUST handle scope correctly."""
        response = wrap_settings_response(
            ok=True,
            sources=["test"],
            scope="organization",
        )
        assert response["metadata"]["scope"] == "organization"

    def test_wrap_response_with_modified_by(self):
        """wrap_settings_response MUST handle modified_by correctly."""
        response = wrap_settings_response(
            ok=True,
            sources=["test"],
            modified_by="user_456",
        )
        assert response["metadata"]["modified_by"] == "user_456"


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestDeterministicBehavior:
    """Tests to ensure deterministic behavior (no randomness in contract)."""

    def test_settings_version_is_stable(self):
        """settings_version MUST be stable across multiple calls."""
        versions = [
            wrap_settings_response(ok=True, sources=["test"])["settings_version"]
            for _ in range(10)
        ]
        assert all(v == SETTINGS_CONTRACT_VERSION for v in versions)

    def test_lifecycle_statuses_are_frozen(self):
        """VALID_SETTINGS_LIFECYCLE_STATUSES MUST be immutable."""
        assert isinstance(VALID_SETTINGS_LIFECYCLE_STATUSES, frozenset)


# =============================================================================
# ALL RESPONSES CONTRACT TEST
# =============================================================================


class TestAllSettingsResponses:
    """Tests that ALL Settings response types include required fields."""

    def test_response_always_has_version(self):
        """All settings responses MUST have settings_version."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "settings_version" in response

    def test_response_always_has_lifecycle(self):
        """All settings responses MUST have lifecycle."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "lifecycle" in response
        assert "status" in response["lifecycle"]
        assert "reason_code" in response["lifecycle"]

    def test_response_always_has_metadata(self):
        """All settings responses MUST have metadata."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "metadata" in response
        assert "sources" in response["metadata"]
        assert "scope" in response["metadata"]
        assert "last_modified_at" in response["metadata"]
        assert "modified_by" in response["metadata"]

    def test_response_always_has_ok(self):
        """All settings responses MUST have ok field."""
        response = wrap_settings_response(ok=True, sources=["test"])
        assert "ok" in response
        assert isinstance(response["ok"], bool)

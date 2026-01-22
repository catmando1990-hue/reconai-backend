"""
CORE STATE SCHEMA VALIDATION TESTS

Tests that verify:
1. All factory outputs match the canonical schema
2. Schema assertion helper catches violations
3. No inline mocks - all tests use canonical factory

CONTRACT VERSION: 1
"""

import pytest
from tests.fixtures import (
    SchemaValidationError,
    assert_valid_core_state,
    core_state_factory,
    empty_org_state,
    partial_org_state,
    full_org_state,
    with_sync_running,
    with_sync_failed,
    with_stale_data,
)
from app.routers.core_state import (
    SYNC_CONTRACT_VERSION,
    VALID_SYNC_STATUSES,
    SyncStatusValidationError,
)


# =============================================================================
# FACTORY OUTPUT VALIDATION
# =============================================================================


class TestFactoryOutputsAreValid:
    """All factory functions MUST produce valid CoreState objects."""

    def test_empty_org_state_is_valid(self, validate_core_state):
        """empty_org_state() produces valid schema."""
        state = empty_org_state()
        validate_core_state(state, "empty_org_state")

    def test_partial_org_state_is_valid(self, validate_core_state):
        """partial_org_state() produces valid schema."""
        state = partial_org_state()
        validate_core_state(state, "partial_org_state")

    def test_full_org_state_is_valid(self, validate_core_state):
        """full_org_state() produces valid schema."""
        state = full_org_state()
        validate_core_state(state, "full_org_state")

    def test_with_sync_running_is_valid(self, validate_core_state):
        """with_sync_running() produces valid schema."""
        state = with_sync_running()
        validate_core_state(state, "with_sync_running")

    def test_with_sync_failed_is_valid(self, validate_core_state):
        """with_sync_failed() produces valid schema."""
        state = with_sync_failed("Test error")
        validate_core_state(state, "with_sync_failed")

    def test_with_stale_data_is_valid(self, validate_core_state):
        """with_stale_data() produces valid schema."""
        state = with_stale_data(hours_ago=48)
        validate_core_state(state, "with_stale_data")

    def test_factory_with_all_parameters_is_valid(self, validate_core_state):
        """core_state_factory with all parameters produces valid schema."""
        state = core_state_factory(
            success=True,
            organization_id="org_test",
            available=True,
            sync_status="success",
            last_completed_at="2024-01-01T00:00:00",
            last_successful_at="2024-01-01T00:00:00",
            stale=False,
            stale_reason=None,
            total_transactions=100,
            total_income=50000.0,
            total_expenses=30000.0,
            plaid_items=[{"item_id": "item_1", "status": "healthy"}],
            recent_transactions=[
                {"id": "tx1", "date": "2024-01-15", "amount": -500, "merchant_name": "Test"}
            ],
            customer_summary={"total_count": 10, "active_count": 8},
            vendor_summary={"total_count": 5, "active_count": 4},
            invoice_summary={"total_count": 20, "draft_count": 2, "sent_count": 3, "paid_count": 15, "overdue_count": 0},
            bill_summary={"total_count": 15, "pending_count": 2, "paid_count": 12, "overdue_count": 1},
        )
        validate_core_state(state, "core_state_factory_full")


class TestFactorySyncVersionCompliance:
    """All factory outputs MUST include correct sync version."""

    def test_empty_org_has_sync_version(self, empty_core_state):
        """Empty org state has sync_version."""
        assert empty_core_state["sync"]["sync_version"] == SYNC_CONTRACT_VERSION

    def test_partial_org_has_sync_version(self, partial_core_state):
        """Partial org state has sync_version."""
        assert partial_core_state["sync"]["sync_version"] == SYNC_CONTRACT_VERSION

    def test_full_org_has_sync_version(self, full_core_state):
        """Full org state has sync_version."""
        assert full_core_state["sync"]["sync_version"] == SYNC_CONTRACT_VERSION

    def test_running_sync_has_sync_version(self, running_sync_state):
        """Running sync state has sync_version."""
        assert running_sync_state["sync"]["sync_version"] == SYNC_CONTRACT_VERSION

    def test_failed_sync_has_sync_version(self, failed_sync_state):
        """Failed sync state has sync_version."""
        assert failed_sync_state["sync"]["sync_version"] == SYNC_CONTRACT_VERSION


class TestFactorySyncStatusCompliance:
    """All factory outputs MUST have valid sync status."""

    @pytest.mark.parametrize("status", list(VALID_SYNC_STATUSES))
    def test_factory_accepts_all_valid_statuses(self, status, validate_core_state):
        """Factory accepts all valid sync status values."""
        state = core_state_factory(sync_status=status)
        assert state["sync"]["status"] == status
        validate_core_state(state, f"factory_with_status_{status}")

    @pytest.mark.parametrize("invalid_status", [
        "NEVER", "Running", "SUCCESS", "FAILED",  # Wrong case
        "pending", "syncing", "idle", "unknown",  # Invalid values
        "", " ", "never ", " never",  # Whitespace variants
    ])
    def test_factory_rejects_invalid_statuses(self, invalid_status):
        """Factory rejects invalid sync status values."""
        with pytest.raises(SyncStatusValidationError):
            core_state_factory(sync_status=invalid_status)


# =============================================================================
# SCHEMA ASSERTION HELPER TESTS
# =============================================================================


class TestSchemaAssertionCatchesMissingFields:
    """Schema assertion MUST fail on missing required fields."""

    def test_missing_success_fails(self, validate_core_state):
        """Missing 'success' field fails."""
        state = full_org_state()
        del state["success"]
        with pytest.raises(SchemaValidationError, match="Missing required field"):
            validate_core_state(state)

    def test_missing_sync_fails(self, validate_core_state):
        """Missing 'sync' field fails."""
        state = full_org_state()
        del state["sync"]
        with pytest.raises(SchemaValidationError, match="Missing required field"):
            validate_core_state(state)

    def test_missing_sync_version_fails(self, validate_core_state):
        """Missing 'sync_version' in sync object fails."""
        state = full_org_state()
        del state["sync"]["sync_version"]
        with pytest.raises(SchemaValidationError, match="Missing required field"):
            validate_core_state(state)

    def test_missing_staleness_fails(self, validate_core_state):
        """Missing 'staleness' field fails."""
        state = full_org_state()
        del state["staleness"]
        with pytest.raises(SchemaValidationError, match="Missing required field"):
            validate_core_state(state)


class TestSchemaAssertionCatchesExtraFields:
    """Schema assertion MUST fail on undocumented fields."""

    def test_extra_top_level_field_fails(self, validate_core_state):
        """Extra top-level field fails."""
        state = full_org_state()
        state["undocumented_field"] = "value"
        with pytest.raises(SchemaValidationError, match="Unexpected field"):
            validate_core_state(state)

    def test_extra_sync_field_fails(self, validate_core_state):
        """Extra field in sync object fails."""
        state = full_org_state()
        state["sync"]["undocumented_field"] = "value"
        with pytest.raises(SchemaValidationError, match="Unexpected field"):
            validate_core_state(state)


class TestSchemaAssertionCatchesTypeViolations:
    """Schema assertion MUST fail on type violations."""

    def test_success_as_string_fails(self, validate_core_state):
        """'success' as string fails."""
        state = full_org_state()
        state["success"] = "true"
        with pytest.raises(SchemaValidationError, match="must be bool"):
            validate_core_state(state)

    def test_sync_version_as_string_fails(self, validate_core_state):
        """'sync_version' as string fails."""
        state = full_org_state()
        state["sync"]["sync_version"] = "1"
        with pytest.raises(SchemaValidationError, match="must be int"):
            validate_core_state(state)


class TestSchemaAssertionCatchesEnumViolations:
    """Schema assertion MUST fail on enum violations."""

    def test_invalid_sync_status_fails(self, validate_core_state):
        """Invalid sync status fails."""
        state = full_org_state()
        state["sync"]["status"] = "invalid_status"
        with pytest.raises(SchemaValidationError, match="must be one of"):
            validate_core_state(state)


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestFactoryDeterminism:
    """Factory outputs MUST be deterministic for same inputs."""

    def test_same_inputs_same_outputs(self):
        """Same factory inputs produce equal outputs (except timestamps)."""
        # Create two states with fixed parameters
        state1 = core_state_factory(
            request_id="fixed_request",
            organization_id="org_test",
            sync_status="success",
            available=True,
        )
        state2 = core_state_factory(
            request_id="fixed_request",
            organization_id="org_test",
            sync_status="success",
            available=True,
        )

        # Core structure should match
        assert state1["request_id"] == state2["request_id"]
        assert state1["organization_id"] == state2["organization_id"]
        assert state1["sync"]["status"] == state2["sync"]["status"]
        assert state1["sync"]["sync_version"] == state2["sync"]["sync_version"]
        assert state1["available"] == state2["available"]

    def test_sync_version_is_stable(self):
        """Sync version is stable across multiple calls."""
        versions = [
            core_state_factory(sync_status="never")["sync"]["sync_version"]
            for _ in range(10)
        ]
        assert all(v == SYNC_CONTRACT_VERSION for v in versions)

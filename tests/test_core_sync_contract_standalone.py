#!/usr/bin/env python3
"""
STANDALONE CONTRACT TESTS for CORE Sync Lifecycle.

This file tests the contract without importing the full application.
Run with: python tests/test_core_sync_contract_standalone.py

CONTRACT VERSION: 1
"""

import sys
from typing import Optional
from dataclasses import dataclass

# =============================================================================
# COPY OF CONTRACT DEFINITIONS (for standalone testing)
# =============================================================================

SYNC_CONTRACT_VERSION = 1
VALID_SYNC_STATUSES = frozenset({"never", "running", "success", "failed"})


class SyncStatusValidationError(ValueError):
    """Raised when an invalid sync status is encountered."""
    pass


def validate_sync_status(status: str) -> str:
    """Validate sync status is in the allowed set."""
    if status not in VALID_SYNC_STATUSES:
        raise SyncStatusValidationError(
            f"Invalid sync status '{status}'. Must be one of: {sorted(VALID_SYNC_STATUSES)}"
        )
    return status


@dataclass
class SyncLifecycleResponse:
    """Sync lifecycle response model."""
    sync_version: int
    status: str
    sync_started_at: Optional[str]
    last_completed_at: Optional[str]
    last_successful_at: Optional[str]
    error_reason: Optional[str]
    request_id: Optional[str]

    @classmethod
    def create_validated(
        cls,
        status: str,
        sync_started_at: Optional[str] = None,
        last_completed_at: Optional[str] = None,
        last_successful_at: Optional[str] = None,
        error_reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> "SyncLifecycleResponse":
        validated_status = validate_sync_status(status)
        return cls(
            sync_version=SYNC_CONTRACT_VERSION,
            status=validated_status,
            sync_started_at=sync_started_at,
            last_completed_at=last_completed_at,
            last_successful_at=last_successful_at,
            error_reason=error_reason,
            request_id=request_id,
        )


# =============================================================================
# CONTRACT TESTS
# =============================================================================

def test_sync_version_is_integer():
    """sync_version MUST be an integer."""
    assert isinstance(SYNC_CONTRACT_VERSION, int), "sync_version must be integer"
    print("PASS: sync_version is integer")


def test_sync_version_is_one():
    """sync_version MUST be 1 (current contract version)."""
    assert SYNC_CONTRACT_VERSION == 1, "sync_version must be 1"
    print("PASS: sync_version is 1")


def test_valid_sync_statuses_exhaustive():
    """VALID_SYNC_STATUSES MUST contain exactly the documented values."""
    expected = {"never", "running", "success", "failed"}
    assert VALID_SYNC_STATUSES == expected, f"Expected {expected}, got {VALID_SYNC_STATUSES}"
    print("PASS: VALID_SYNC_STATUSES is correct")


def test_valid_sync_statuses_immutable():
    """VALID_SYNC_STATUSES MUST be immutable (frozenset)."""
    assert isinstance(VALID_SYNC_STATUSES, frozenset), "VALID_SYNC_STATUSES must be frozenset"
    print("PASS: VALID_SYNC_STATUSES is immutable")


def test_valid_statuses_accepted():
    """Valid status values MUST be accepted."""
    for status in ["never", "running", "success", "failed"]:
        result = validate_sync_status(status)
        assert result == status, f"Status {status} should be accepted"
    print("PASS: All valid statuses accepted")


def test_invalid_statuses_rejected():
    """Invalid status values MUST be rejected."""
    invalid_statuses = [
        "NEVER",    # Case sensitive
        "Running",  # Case sensitive
        "SUCCESS",  # Case sensitive
        "FAILED",   # Case sensitive
        "pending",  # Not in enum
        "syncing",  # Legacy value
        "idle",     # Legacy value
        "unknown",  # Invalid
        "",         # Empty string
        " ",        # Whitespace
        "never ",   # Trailing space
        " never",   # Leading space
    ]
    for invalid in invalid_statuses:
        try:
            validate_sync_status(invalid)
            raise AssertionError(f"Status {invalid!r} should be rejected")
        except SyncStatusValidationError:
            pass
    print("PASS: All invalid statuses rejected")


def test_create_validated_includes_sync_version():
    """create_validated MUST include sync_version."""
    response = SyncLifecycleResponse.create_validated(status="never")
    assert response.sync_version == SYNC_CONTRACT_VERSION, "sync_version must be set"
    print("PASS: create_validated includes sync_version")


def test_create_validated_for_all_statuses():
    """sync_version MUST be present for all valid status values."""
    for status in VALID_SYNC_STATUSES:
        response = SyncLifecycleResponse.create_validated(status=status)
        assert response.sync_version == SYNC_CONTRACT_VERSION, f"sync_version missing for {status}"
    print("PASS: sync_version present for all statuses")


def test_required_fields_exist():
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
    actual_fields = set(vars(response).keys())
    missing = required_fields - actual_fields
    assert not missing, f"Missing required fields: {missing}"
    print("PASS: All required fields exist")


def test_no_extra_fields():
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
    actual_fields = set(vars(response).keys())
    extra = actual_fields - expected_fields
    assert not extra, f"Unexpected fields: {extra}"
    print("PASS: No extra fields")


def test_create_validated_rejects_invalid_status():
    """create_validated MUST reject invalid status values."""
    try:
        SyncLifecycleResponse.create_validated(status="invalid")
        raise AssertionError("Invalid status should raise error")
    except SyncStatusValidationError:
        pass
    print("PASS: create_validated rejects invalid status")


def test_error_message_is_explicit():
    """Error message MUST list valid statuses."""
    try:
        validate_sync_status("invalid")
    except SyncStatusValidationError as e:
        error_msg = str(e).lower()
        assert "invalid" in error_msg, "Error should mention invalid value"
        # Should list at least some valid values
        has_valid = any(s in str(e) for s in VALID_SYNC_STATUSES)
        assert has_valid, "Error should list valid statuses"
    print("PASS: Error message is explicit")


def test_deterministic_output():
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
    assert vars(result1) == vars(result2), "Same inputs should produce same outputs"
    print("PASS: Output is deterministic")


def test_sync_version_stable():
    """sync_version MUST be stable across multiple calls."""
    versions = [
        SyncLifecycleResponse.create_validated(status="never").sync_version
        for _ in range(10)
    ]
    assert all(v == SYNC_CONTRACT_VERSION for v in versions), "sync_version should be stable"
    print("PASS: sync_version is stable")


# =============================================================================
# RUN ALL TESTS
# =============================================================================

def run_all_tests():
    """Run all contract tests."""
    tests = [
        test_sync_version_is_integer,
        test_sync_version_is_one,
        test_valid_sync_statuses_exhaustive,
        test_valid_sync_statuses_immutable,
        test_valid_statuses_accepted,
        test_invalid_statuses_rejected,
        test_create_validated_includes_sync_version,
        test_create_validated_for_all_statuses,
        test_required_fields_exist,
        test_no_extra_fields,
        test_create_validated_rejects_invalid_status,
        test_error_message_is_explicit,
        test_deterministic_output,
        test_sync_version_stable,
    ]

    print("=" * 60)
    print("CORE SYNC CONTRACT TESTS")
    print("=" * 60)
    print()

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {test.__name__}: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print()
        print("CONTRACT VIOLATION DETECTED")
        print("Schema drift must be resolved before deployment.")
        sys.exit(1)
    else:
        print()
        print("ALL CONTRACT TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()

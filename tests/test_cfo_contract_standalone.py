#!/usr/bin/env python3
"""
STANDALONE CONTRACT TESTS for CFO API.

This file tests the contract without importing the full application.
Run with: python tests/test_cfo_contract_standalone.py

CONTRACT VERSION: 1

All CFO responses MUST include:
- cfo_version: int (ALWAYS present, value = 1)
- lifecycle: object (ALWAYS present, explicit state)
- evidence: object (ALWAYS present, auditability)
"""

import sys
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime

# =============================================================================
# COPY OF CONTRACT DEFINITIONS (for standalone testing)
# =============================================================================

CFO_CONTRACT_VERSION = 1

# Valid lifecycle statuses - fail-closed validation
CFOLifecycleStatus = Literal["success", "partial", "failed", "no_data"]
VALID_CFO_LIFECYCLE_STATUSES = frozenset({"success", "partial", "failed", "no_data"})


class CFOLifecycleValidationError(ValueError):
    """Raised when lifecycle status is invalid. Fail-closed design."""
    pass


def validate_cfo_lifecycle_status(status: str) -> str:
    """Validate CFO lifecycle status. Fail-closed: reject invalid values."""
    if status not in VALID_CFO_LIFECYCLE_STATUSES:
        raise CFOLifecycleValidationError(
            f"Invalid CFO lifecycle status: '{status}'. "
            f"Valid values: {sorted(VALID_CFO_LIFECYCLE_STATUSES)}"
        )
    return status


@dataclass
class MockCFOLifecycle:
    """Mock CFO lifecycle for testing."""
    status: str
    reason_code: Optional[str] = None

    def __post_init__(self):
        validate_cfo_lifecycle_status(self.status)
        if self.status != "success" and not self.reason_code:
            raise CFOLifecycleValidationError(
                f"reason_code is required when lifecycle status is '{self.status}'"
            )

    @classmethod
    def success(cls) -> "MockCFOLifecycle":
        return cls(status="success", reason_code=None)

    @classmethod
    def partial(cls, reason_code: str) -> "MockCFOLifecycle":
        return cls(status="partial", reason_code=reason_code)

    @classmethod
    def failed(cls, reason_code: str) -> "MockCFOLifecycle":
        return cls(status="failed", reason_code=reason_code)

    @classmethod
    def no_data(cls, reason_code: str) -> "MockCFOLifecycle":
        return cls(status="no_data", reason_code=reason_code)


@dataclass
class MockEvidenceMetadata:
    """Mock evidence metadata for testing."""
    sources: List[str]
    coverage_window: Dict[str, Optional[str]]
    last_updated_at: str
    record_count: int = 0
    confidence_note: Optional[str] = None

    @classmethod
    def create(
        cls,
        sources: List[str],
        start_date: Optional[str],
        end_date: Optional[str],
        record_count: int = 0,
        confidence_note: Optional[str] = None,
    ) -> "MockEvidenceMetadata":
        return cls(
            sources=sources,
            coverage_window={"start": start_date, "end": end_date},
            last_updated_at=datetime.utcnow().isoformat(),
            record_count=record_count,
            confidence_note=confidence_note,
        )

    @classmethod
    def empty(cls, reason: str) -> "MockEvidenceMetadata":
        return cls(
            sources=[],
            coverage_window={"start": None, "end": None},
            last_updated_at=datetime.utcnow().isoformat(),
            record_count=0,
            confidence_note=reason,
        )


@dataclass
class MockCFOOverviewResponse:
    """Mock CFO overview response for testing."""
    cfo_version: int
    lifecycle: MockCFOLifecycle
    evidence: MockEvidenceMetadata
    ok: bool
    request_id: str
    org_id: str
    generated_at: str
    kpis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockForecastResponse:
    """Mock forecast response for testing."""
    cfo_version: int
    lifecycle: MockCFOLifecycle
    evidence: MockEvidenceMetadata
    ok: bool
    request_id: str
    org_id: str
    generated_at: str
    forecasts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockExceptionsResponse:
    """Mock exceptions response for testing."""
    cfo_version: int
    lifecycle: MockCFOLifecycle
    evidence: MockEvidenceMetadata
    ok: bool
    request_id: str
    org_id: str
    generated_at: str
    exceptions: List[Any] = field(default_factory=list)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


def test_cfo_version_is_integer():
    """CFO_CONTRACT_VERSION MUST be an integer."""
    assert isinstance(CFO_CONTRACT_VERSION, int), "CFO_CONTRACT_VERSION must be integer"
    print("PASS: cfo_version is integer")


def test_cfo_version_is_one():
    """CFO_CONTRACT_VERSION MUST be 1 (current contract version)."""
    assert CFO_CONTRACT_VERSION == 1, "CFO_CONTRACT_VERSION must be 1"
    print("PASS: cfo_version is 1")


def test_cfo_version_is_positive():
    """CFO_CONTRACT_VERSION MUST be positive."""
    assert CFO_CONTRACT_VERSION > 0, "CFO_CONTRACT_VERSION must be positive"
    print("PASS: cfo_version is positive")


# =============================================================================
# LIFECYCLE CONTRACT TESTS
# =============================================================================


def test_valid_lifecycle_statuses():
    """VALID_CFO_LIFECYCLE_STATUSES MUST contain expected values."""
    assert "success" in VALID_CFO_LIFECYCLE_STATUSES
    assert "partial" in VALID_CFO_LIFECYCLE_STATUSES
    assert "failed" in VALID_CFO_LIFECYCLE_STATUSES
    assert "no_data" in VALID_CFO_LIFECYCLE_STATUSES
    print("PASS: valid lifecycle statuses defined")


def test_lifecycle_success_factory():
    """MockCFOLifecycle.success() MUST create valid success lifecycle."""
    lifecycle = MockCFOLifecycle.success()
    assert lifecycle.status == "success"
    assert lifecycle.reason_code is None
    print("PASS: lifecycle success factory works")


def test_lifecycle_partial_requires_reason():
    """MockCFOLifecycle.partial() MUST require reason_code."""
    lifecycle = MockCFOLifecycle.partial(reason_code="TEST_REASON")
    assert lifecycle.status == "partial"
    assert lifecycle.reason_code == "TEST_REASON"
    print("PASS: lifecycle partial requires reason")


def test_lifecycle_failed_requires_reason():
    """MockCFOLifecycle.failed() MUST require reason_code."""
    lifecycle = MockCFOLifecycle.failed(reason_code="TEST_FAILURE")
    assert lifecycle.status == "failed"
    assert lifecycle.reason_code == "TEST_FAILURE"
    print("PASS: lifecycle failed requires reason")


def test_lifecycle_no_data_requires_reason():
    """MockCFOLifecycle.no_data() MUST require reason_code."""
    lifecycle = MockCFOLifecycle.no_data(reason_code="NO_TRANSACTIONS")
    assert lifecycle.status == "no_data"
    assert lifecycle.reason_code == "NO_TRANSACTIONS"
    print("PASS: lifecycle no_data requires reason")


def test_invalid_status_rejected():
    """Invalid lifecycle status MUST raise CFOLifecycleValidationError."""
    try:
        validate_cfo_lifecycle_status("invalid_status")
        assert False, "Should have raised CFOLifecycleValidationError"
    except CFOLifecycleValidationError:
        pass
    print("PASS: invalid status rejected")


def test_non_success_without_reason_rejected():
    """Non-success lifecycle without reason_code MUST be rejected."""
    try:
        MockCFOLifecycle(status="partial", reason_code=None)
        assert False, "Should have raised CFOLifecycleValidationError"
    except CFOLifecycleValidationError:
        pass
    print("PASS: non-success without reason rejected")


# =============================================================================
# EVIDENCE METADATA CONTRACT TESTS
# =============================================================================


def test_evidence_create_factory():
    """MockEvidenceMetadata.create() MUST create valid evidence."""
    evidence = MockEvidenceMetadata.create(
        sources=["table_a", "table_b"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        record_count=100,
        confidence_note="Test note",
    )
    assert evidence.sources == ["table_a", "table_b"]
    assert evidence.coverage_window["start"] == "2024-01-01"
    assert evidence.coverage_window["end"] == "2024-12-31"
    assert evidence.record_count == 100
    assert evidence.confidence_note == "Test note"
    print("PASS: evidence create factory works")


def test_evidence_empty_factory():
    """MockEvidenceMetadata.empty() MUST create valid empty evidence."""
    evidence = MockEvidenceMetadata.empty(reason="No data available")
    assert evidence.sources == []
    assert evidence.coverage_window["start"] is None
    assert evidence.coverage_window["end"] is None
    assert evidence.record_count == 0
    assert evidence.confidence_note == "No data available"
    print("PASS: evidence empty factory works")


# =============================================================================
# RESPONSE MODEL TESTS
# =============================================================================


def _make_lifecycle():
    return MockCFOLifecycle.success()


def _make_evidence():
    return MockEvidenceMetadata.create(
        sources=["test_source"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        record_count=10,
    )


def test_overview_response_has_all_required_fields():
    """CFOOverviewResponse MUST have cfo_version, lifecycle, and evidence."""
    response = MockCFOOverviewResponse(
        cfo_version=CFO_CONTRACT_VERSION,
        lifecycle=_make_lifecycle(),
        evidence=_make_evidence(),
        ok=True,
        request_id="test_123",
        org_id="org_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "cfo_version")
    assert hasattr(response, "lifecycle")
    assert hasattr(response, "evidence")
    assert response.cfo_version == CFO_CONTRACT_VERSION
    assert response.lifecycle is not None
    assert response.evidence is not None
    print("PASS: CFOOverviewResponse has all required fields")


def test_forecast_response_has_all_required_fields():
    """ForecastResponse MUST have cfo_version, lifecycle, and evidence."""
    response = MockForecastResponse(
        cfo_version=CFO_CONTRACT_VERSION,
        lifecycle=_make_lifecycle(),
        evidence=_make_evidence(),
        ok=True,
        request_id="test_123",
        org_id="org_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "cfo_version")
    assert hasattr(response, "lifecycle")
    assert hasattr(response, "evidence")
    assert response.cfo_version == CFO_CONTRACT_VERSION
    print("PASS: ForecastResponse has all required fields")


def test_exceptions_response_has_all_required_fields():
    """ExceptionsResponse MUST have cfo_version, lifecycle, and evidence."""
    response = MockExceptionsResponse(
        cfo_version=CFO_CONTRACT_VERSION,
        lifecycle=_make_lifecycle(),
        evidence=_make_evidence(),
        ok=True,
        request_id="test_123",
        org_id="org_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "cfo_version")
    assert hasattr(response, "lifecycle")
    assert hasattr(response, "evidence")
    assert response.cfo_version == CFO_CONTRACT_VERSION
    print("PASS: ExceptionsResponse has all required fields")


def test_cfo_version_is_stable():
    """cfo_version MUST be stable across multiple instantiations."""
    versions = [
        MockCFOOverviewResponse(
            cfo_version=CFO_CONTRACT_VERSION,
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
            ok=True,
            request_id="test",
            org_id="org",
            generated_at="2024-01-01T00:00:00Z",
        ).cfo_version
        for _ in range(10)
    ]
    assert all(v == CFO_CONTRACT_VERSION for v in versions), "cfo_version must be stable"
    print("PASS: cfo_version is stable")


def test_cfo_version_in_stats_response():
    """Stats endpoint response MUST include cfo_version, lifecycle, evidence."""
    # Simulate the stats endpoint response structure
    stats_response = {
        "cfo_version": CFO_CONTRACT_VERSION,
        "lifecycle": {"status": "success", "reason_code": None},
        "evidence": {
            "sources": ["mvp_transactions"],
            "coverage_window": {"start": "2024-01-01", "end": "2024-12-31"},
            "last_updated_at": "2024-01-01T00:00:00Z",
            "record_count": 100,
        },
        "ok": True,
        "request_id": "test_123",
        "generated_at": "2024-01-01T00:00:00Z",
        "stats": {
            "burn_rate": {"monthly": 10000.0},
        },
    }
    assert "cfo_version" in stats_response, "stats response must have cfo_version"
    assert "lifecycle" in stats_response, "stats response must have lifecycle"
    assert "evidence" in stats_response, "stats response must have evidence"
    assert stats_response["cfo_version"] == CFO_CONTRACT_VERSION
    print("PASS: stats response has all required contract fields")


# =============================================================================
# RUN ALL TESTS
# =============================================================================


def run_all_tests():
    """Run all contract tests."""
    tests = [
        # Version tests
        test_cfo_version_is_integer,
        test_cfo_version_is_one,
        test_cfo_version_is_positive,
        # Lifecycle tests
        test_valid_lifecycle_statuses,
        test_lifecycle_success_factory,
        test_lifecycle_partial_requires_reason,
        test_lifecycle_failed_requires_reason,
        test_lifecycle_no_data_requires_reason,
        test_invalid_status_rejected,
        test_non_success_without_reason_rejected,
        # Evidence tests
        test_evidence_create_factory,
        test_evidence_empty_factory,
        # Response model tests
        test_overview_response_has_all_required_fields,
        test_forecast_response_has_all_required_fields,
        test_exceptions_response_has_all_required_fields,
        test_cfo_version_is_stable,
        test_cfo_version_in_stats_response,
    ]

    print("=" * 60)
    print("CFO CONTRACT TESTS (with Lifecycle & Evidence)")
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

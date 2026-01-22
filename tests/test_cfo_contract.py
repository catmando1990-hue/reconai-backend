# tests/test_cfo_contract.py
"""
CONTRACT TESTS for CFO API.

These tests LOCK the backend contract for CFO endpoints.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

All CFO responses MUST include:
- cfo_version: int (ALWAYS present, value = 1)
- lifecycle: CFOLifecycle (ALWAYS present, explicit state)
- evidence: EvidenceMetadata (ALWAYS present, auditability)
"""

import pytest
from app.cfo.models import (
    CFOOverviewResponse,
    ForecastResponse,
    ExceptionsResponse,
    CFO_CONTRACT_VERSION,
    ForecastSeries,
    CFOLifecycle,
    CFOLifecycleValidationError,
    EvidenceMetadata,
    VALID_CFO_LIFECYCLE_STATUSES,
    validate_cfo_lifecycle_status,
)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


class TestCFOContractVersion:
    """Tests for cfo_version constant and field presence."""

    def test_cfo_version_is_integer(self):
        """CFO_CONTRACT_VERSION MUST be an integer."""
        assert isinstance(CFO_CONTRACT_VERSION, int)

    def test_cfo_version_is_positive(self):
        """CFO_CONTRACT_VERSION MUST be positive."""
        assert CFO_CONTRACT_VERSION > 0

    def test_cfo_version_current_value(self):
        """CFO_CONTRACT_VERSION MUST be 1 (current contract version)."""
        assert CFO_CONTRACT_VERSION == 1


# =============================================================================
# CFO OVERVIEW RESPONSE TESTS
# =============================================================================


def _make_lifecycle():
    """Helper to create a valid lifecycle for testing."""
    return CFOLifecycle.success()


def _make_evidence():
    """Helper to create valid evidence metadata for testing."""
    return EvidenceMetadata.create(
        sources=["test_source"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        record_count=10,
    )


class TestCFOOverviewResponse:
    """Tests for CFOOverviewResponse contract."""

    def test_cfo_version_always_present(self):
        """cfo_version MUST always be present in CFOOverviewResponse."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "cfo_version")
        assert response.cfo_version == CFO_CONTRACT_VERSION

    def test_cfo_version_in_serialized_output(self):
        """cfo_version MUST be present in serialized JSON output."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        data = response.model_dump()
        assert "cfo_version" in data
        assert data["cfo_version"] == CFO_CONTRACT_VERSION

    def test_cfo_version_is_integer_in_response(self):
        """cfo_version MUST be an integer in the response."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert isinstance(response.cfo_version, int)

    def test_lifecycle_always_present(self):
        """lifecycle MUST always be present in CFOOverviewResponse."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "lifecycle")
        assert response.lifecycle is not None

    def test_evidence_always_present(self):
        """evidence MUST always be present in CFOOverviewResponse."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "evidence")
        assert response.evidence is not None


# =============================================================================
# FORECAST RESPONSE TESTS
# =============================================================================


class TestForecastResponse:
    """Tests for ForecastResponse contract."""

    def test_cfo_version_always_present(self):
        """cfo_version MUST always be present in ForecastResponse."""
        response = ForecastResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "cfo_version")
        assert response.cfo_version == CFO_CONTRACT_VERSION

    def test_cfo_version_in_serialized_output(self):
        """cfo_version MUST be present in serialized JSON output."""
        response = ForecastResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        data = response.model_dump()
        assert "cfo_version" in data
        assert data["cfo_version"] == CFO_CONTRACT_VERSION

    def test_cfo_version_is_integer_in_response(self):
        """cfo_version MUST be an integer in the response."""
        response = ForecastResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert isinstance(response.cfo_version, int)

    def test_lifecycle_always_present(self):
        """lifecycle MUST always be present in ForecastResponse."""
        response = ForecastResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "lifecycle")
        assert response.lifecycle is not None

    def test_evidence_always_present(self):
        """evidence MUST always be present in ForecastResponse."""
        response = ForecastResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "evidence")
        assert response.evidence is not None


# =============================================================================
# EXCEPTIONS RESPONSE TESTS
# =============================================================================


class TestExceptionsResponse:
    """Tests for ExceptionsResponse contract."""

    def test_cfo_version_always_present(self):
        """cfo_version MUST always be present in ExceptionsResponse."""
        response = ExceptionsResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "cfo_version")
        assert response.cfo_version == CFO_CONTRACT_VERSION

    def test_cfo_version_in_serialized_output(self):
        """cfo_version MUST be present in serialized JSON output."""
        response = ExceptionsResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        data = response.model_dump()
        assert "cfo_version" in data
        assert data["cfo_version"] == CFO_CONTRACT_VERSION

    def test_cfo_version_is_integer_in_response(self):
        """cfo_version MUST be an integer in the response."""
        response = ExceptionsResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert isinstance(response.cfo_version, int)

    def test_lifecycle_always_present(self):
        """lifecycle MUST always be present in ExceptionsResponse."""
        response = ExceptionsResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "lifecycle")
        assert response.lifecycle is not None

    def test_evidence_always_present(self):
        """evidence MUST always be present in ExceptionsResponse."""
        response = ExceptionsResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert hasattr(response, "evidence")
        assert response.evidence is not None


# =============================================================================
# ALL RESPONSES CONTRACT TEST
# =============================================================================


class TestAllCFOResponses:
    """Tests that ALL CFO response types include required contract fields."""

    def test_all_response_models_have_cfo_version(self):
        """All CFO response models MUST have cfo_version field."""
        response_models = [
            CFOOverviewResponse,
            ForecastResponse,
            ExceptionsResponse,
        ]

        for model in response_models:
            # Check field exists in model
            field_names = model.model_fields.keys()
            assert "cfo_version" in field_names, (
                f"{model.__name__} MUST have cfo_version field"
            )

    def test_all_response_models_have_lifecycle(self):
        """All CFO response models MUST have lifecycle field."""
        response_models = [
            CFOOverviewResponse,
            ForecastResponse,
            ExceptionsResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "lifecycle" in field_names, (
                f"{model.__name__} MUST have lifecycle field"
            )

    def test_all_response_models_have_evidence(self):
        """All CFO response models MUST have evidence field."""
        response_models = [
            CFOOverviewResponse,
            ForecastResponse,
            ExceptionsResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "evidence" in field_names, (
                f"{model.__name__} MUST have evidence field"
            )

    def test_all_response_models_default_to_contract_version(self):
        """All CFO response models MUST default cfo_version to CFO_CONTRACT_VERSION."""
        # CFOOverviewResponse
        overview = CFOOverviewResponse(
            request_id="test",
            org_id="org",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert overview.cfo_version == CFO_CONTRACT_VERSION

        # ForecastResponse
        forecast = ForecastResponse(
            request_id="test",
            org_id="org",
            generated_at="2024-01-01T00:00:00Z",
            forecasts=ForecastSeries(),
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert forecast.cfo_version == CFO_CONTRACT_VERSION

        # ExceptionsResponse
        exceptions = ExceptionsResponse(
            request_id="test",
            org_id="org",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert exceptions.cfo_version == CFO_CONTRACT_VERSION


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestDeterministicBehavior:
    """Tests to ensure deterministic behavior (no randomness in contract)."""

    def test_cfo_version_is_stable(self):
        """cfo_version MUST be stable across multiple instantiations."""
        versions = [
            CFOOverviewResponse(
                request_id="test",
                org_id="org",
                generated_at="2024-01-01T00:00:00Z",
                lifecycle=_make_lifecycle(),
                evidence=_make_evidence(),
            ).cfo_version
            for _ in range(10)
        ]
        assert all(v == CFO_CONTRACT_VERSION for v in versions)

    def test_same_input_produces_same_version(self):
        """Same inputs MUST produce identical cfo_version."""
        response1 = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        response2 = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=_make_evidence(),
        )
        assert response1.cfo_version == response2.cfo_version


# =============================================================================
# LIFECYCLE CONTRACT TESTS
# =============================================================================


class TestCFOLifecycleContract:
    """Tests for CFO lifecycle enum validation and behavior."""

    def test_valid_lifecycle_statuses(self):
        """VALID_CFO_LIFECYCLE_STATUSES MUST contain expected values."""
        assert "success" in VALID_CFO_LIFECYCLE_STATUSES
        assert "partial" in VALID_CFO_LIFECYCLE_STATUSES
        assert "failed" in VALID_CFO_LIFECYCLE_STATUSES
        assert "no_data" in VALID_CFO_LIFECYCLE_STATUSES

    def test_lifecycle_success_factory(self):
        """CFOLifecycle.success() MUST create valid success lifecycle."""
        lifecycle = CFOLifecycle.success()
        assert lifecycle.status == "success"
        assert lifecycle.reason_code is None

    def test_lifecycle_partial_requires_reason(self):
        """CFOLifecycle.partial() MUST require reason_code."""
        lifecycle = CFOLifecycle.partial(reason_code="TEST_REASON")
        assert lifecycle.status == "partial"
        assert lifecycle.reason_code == "TEST_REASON"

    def test_lifecycle_failed_requires_reason(self):
        """CFOLifecycle.failed() MUST require reason_code."""
        lifecycle = CFOLifecycle.failed(reason_code="TEST_FAILURE")
        assert lifecycle.status == "failed"
        assert lifecycle.reason_code == "TEST_FAILURE"

    def test_lifecycle_no_data_requires_reason(self):
        """CFOLifecycle.no_data() MUST require reason_code."""
        lifecycle = CFOLifecycle.no_data(reason_code="NO_TRANSACTIONS")
        assert lifecycle.status == "no_data"
        assert lifecycle.reason_code == "NO_TRANSACTIONS"

    def test_invalid_status_rejected(self):
        """Invalid lifecycle status MUST raise CFOLifecycleValidationError."""
        with pytest.raises(CFOLifecycleValidationError):
            validate_cfo_lifecycle_status("invalid_status")

    def test_non_success_without_reason_rejected(self):
        """Non-success lifecycle without reason_code MUST be rejected."""
        with pytest.raises(CFOLifecycleValidationError):
            CFOLifecycle(status="partial", reason_code=None)

    def test_lifecycle_in_serialized_output(self):
        """lifecycle MUST be present in serialized JSON output."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=CFOLifecycle.partial(reason_code="LOW_CONFIDENCE"),
            evidence=_make_evidence(),
        )
        data = response.model_dump()
        assert "lifecycle" in data
        assert data["lifecycle"]["status"] == "partial"
        assert data["lifecycle"]["reason_code"] == "LOW_CONFIDENCE"


# =============================================================================
# EVIDENCE METADATA CONTRACT TESTS
# =============================================================================


class TestEvidenceMetadataContract:
    """Tests for evidence metadata presence and structure."""

    def test_evidence_has_required_fields(self):
        """EvidenceMetadata MUST have sources, coverage_window, last_updated_at."""
        evidence = _make_evidence()
        assert hasattr(evidence, "sources")
        assert hasattr(evidence, "coverage_window")
        assert hasattr(evidence, "last_updated_at")
        assert hasattr(evidence, "record_count")

    def test_evidence_create_factory(self):
        """EvidenceMetadata.create() MUST create valid evidence."""
        evidence = EvidenceMetadata.create(
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

    def test_evidence_empty_factory(self):
        """EvidenceMetadata.empty() MUST create valid empty evidence."""
        evidence = EvidenceMetadata.empty(reason="No data available")
        assert evidence.sources == []
        assert evidence.coverage_window["start"] is None
        assert evidence.coverage_window["end"] is None
        assert evidence.record_count == 0
        assert evidence.confidence_note == "No data available"

    def test_evidence_in_serialized_output(self):
        """evidence MUST be present in serialized JSON output."""
        response = CFOOverviewResponse(
            request_id="test_123",
            org_id="org_123",
            generated_at="2024-01-01T00:00:00Z",
            lifecycle=_make_lifecycle(),
            evidence=EvidenceMetadata.create(
                sources=["mvp_transactions"],
                start_date="2024-01-01",
                end_date="2024-01-31",
                record_count=50,
            ),
        )
        data = response.model_dump()
        assert "evidence" in data
        assert data["evidence"]["sources"] == ["mvp_transactions"]
        assert data["evidence"]["record_count"] == 50

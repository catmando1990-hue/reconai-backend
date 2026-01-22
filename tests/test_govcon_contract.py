# tests/test_govcon_contract.py
"""
CONTRACT TESTS for GovCon API.

These tests LOCK the backend contract for GovCon/DCAA endpoints.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

All GovCon responses MUST include:
- govcon_version: int (ALWAYS present, value = 1)
- lifecycle: dict (ALWAYS present, status + reason_code)
- evidence: dict (ALWAYS present, metadata for auditability)
"""

import pytest
from app.govcon.contract import (
    GOVCON_CONTRACT_VERSION,
    VALID_GOVCON_LIFECYCLE_STATUSES,
    create_govcon_lifecycle,
    create_govcon_evidence,
    wrap_govcon_response,
    GovConLifecycle,
    GovConEvidenceMetadata,
)
from app.govcon.models import (
    GovConTransactionsResponse,
    ExportPreviewResponse,
    Lifecycle,
    EvidenceMetadata,
    CoverageWindow,
    GovConTransactionOverlay,
    ExportPreviewItem,
)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


class TestGovConContractVersion:
    """Tests for GOVCON_CONTRACT_VERSION constant."""

    def test_govcon_version_is_integer(self):
        """GOVCON_CONTRACT_VERSION MUST be an integer."""
        assert isinstance(GOVCON_CONTRACT_VERSION, int)

    def test_govcon_version_is_positive(self):
        """GOVCON_CONTRACT_VERSION MUST be positive."""
        assert GOVCON_CONTRACT_VERSION > 0

    def test_govcon_version_current_value(self):
        """GOVCON_CONTRACT_VERSION MUST be 1 (current contract version)."""
        assert GOVCON_CONTRACT_VERSION == 1


# =============================================================================
# LIFECYCLE VALIDATION TESTS
# =============================================================================


class TestGovConLifecycleValidation:
    """Tests for lifecycle validation logic."""

    def test_lifecycle_valid_statuses(self):
        """VALID_GOVCON_LIFECYCLE_STATUSES MUST contain expected values."""
        expected = {"success", "partial", "failed", "no_data"}
        assert VALID_GOVCON_LIFECYCLE_STATUSES == expected

    def test_lifecycle_requires_reason_code_for_non_success(self):
        """reason_code MUST be present when status != success."""
        for status in ["partial", "failed", "no_data"]:
            with pytest.raises(ValueError, match="reason_code is required"):
                create_govcon_lifecycle(status)

    def test_lifecycle_clears_reason_code_for_success(self):
        """reason_code MUST be None for success status."""
        lifecycle = create_govcon_lifecycle("success", "SHOULD_BE_CLEARED")
        assert lifecycle["reason_code"] is None

    def test_lifecycle_rejects_invalid_status(self):
        """Invalid status values MUST be rejected."""
        with pytest.raises(ValueError, match="Invalid GovCon lifecycle status"):
            create_govcon_lifecycle("invalid_status")

    def test_lifecycle_accepts_all_valid_statuses(self):
        """All valid statuses MUST be accepted."""
        for status in ["success", "partial", "failed", "no_data"]:
            if status == "success":
                lifecycle = create_govcon_lifecycle(status)
            else:
                lifecycle = create_govcon_lifecycle(status, "TEST_REASON")
            assert lifecycle["status"] == status


# =============================================================================
# EVIDENCE METADATA TESTS
# =============================================================================


class TestGovConEvidenceMetadata:
    """Tests for evidence metadata validation logic."""

    def test_evidence_includes_documents(self):
        """Evidence MUST include documents array."""
        evidence = create_govcon_evidence(["source"], documents=["FAR_31_201", "CAS_418"])
        assert "documents" in evidence
        assert evidence["documents"] == ["FAR_31_201", "CAS_418"]

    def test_evidence_includes_documents_default_empty(self):
        """Evidence documents MUST default to empty array."""
        evidence = create_govcon_evidence(["source"])
        assert "documents" in evidence
        assert evidence["documents"] == []

    def test_evidence_includes_sources(self):
        """Evidence MUST include sources list."""
        evidence = create_govcon_evidence(["source1", "source2"])
        assert "sources" in evidence
        assert evidence["sources"] == ["source1", "source2"]

    def test_evidence_includes_coverage_window(self):
        """Evidence MUST include coverage_window."""
        evidence = create_govcon_evidence(["source"])
        assert "coverage_window" in evidence
        assert "start" in evidence["coverage_window"]
        assert "end" in evidence["coverage_window"]

    def test_evidence_includes_last_verified_at(self):
        """Evidence MUST include last_verified_at timestamp."""
        evidence = create_govcon_evidence(["source"])
        assert "last_verified_at" in evidence
        assert isinstance(evidence["last_verified_at"], str)

    def test_evidence_includes_dcaa_compliant(self):
        """Evidence MUST include dcaa_compliant boolean."""
        evidence = create_govcon_evidence(["source"])
        assert "dcaa_compliant" in evidence
        assert isinstance(evidence["dcaa_compliant"], bool)


# =============================================================================
# WRAP GOVCON RESPONSE TESTS
# =============================================================================


class TestWrapGovConResponse:
    """Tests for wrap_govcon_response function."""

    def test_wrap_response_includes_version(self):
        """wrap_govcon_response MUST return govcon_version."""
        response = wrap_govcon_response(ok=True, sources=["test"])
        assert "govcon_version" in response
        assert response["govcon_version"] == GOVCON_CONTRACT_VERSION

    def test_wrap_response_includes_lifecycle(self):
        """wrap_govcon_response MUST return lifecycle."""
        response = wrap_govcon_response(ok=True, sources=["test"])
        assert "lifecycle" in response
        assert "status" in response["lifecycle"]
        assert response["lifecycle"]["status"] == "success"

    def test_wrap_response_includes_evidence(self):
        """wrap_govcon_response MUST return evidence metadata."""
        response = wrap_govcon_response(ok=True, sources=["test"])
        assert "evidence" in response
        assert "documents" in response["evidence"]
        assert "sources" in response["evidence"]
        assert "coverage_window" in response["evidence"]
        assert "last_verified_at" in response["evidence"]
        assert "dcaa_compliant" in response["evidence"]

    def test_wrap_response_version_is_integer(self):
        """govcon_version in wrap_govcon_response MUST be integer."""
        response = wrap_govcon_response(ok=True, sources=["test"])
        assert isinstance(response["govcon_version"], int)

    def test_wrap_response_with_extra_fields_preserves_version(self):
        """Extra fields MUST not override govcon_version."""
        response = wrap_govcon_response(
            ok=True,
            sources=["test"],
            custom_field="value",
        )
        assert "govcon_version" in response
        assert response["govcon_version"] == GOVCON_CONTRACT_VERSION
        assert response["custom_field"] == "value"

    def test_wrap_response_with_failed_lifecycle(self):
        """wrap_govcon_response MUST handle failed lifecycle correctly."""
        response = wrap_govcon_response(
            ok=False,
            sources=["test"],
            lifecycle_status="failed",
            lifecycle_reason="TEST_FAILURE",
        )
        assert response["lifecycle"]["status"] == "failed"
        assert response["lifecycle"]["reason_code"] == "TEST_FAILURE"


# =============================================================================
# GOVCON TRANSACTIONS RESPONSE MODEL TESTS
# =============================================================================


class TestGovConTransactionsResponseModel:
    """Tests for GovConTransactionsResponse Pydantic model."""

    def test_transactions_response_has_version_field(self):
        """GovConTransactionsResponse MUST have govcon_version field."""
        assert "govcon_version" in GovConTransactionsResponse.model_fields

    def test_transactions_response_has_lifecycle_field(self):
        """GovConTransactionsResponse MUST have lifecycle field."""
        assert "lifecycle" in GovConTransactionsResponse.model_fields

    def test_transactions_response_has_evidence_field(self):
        """GovConTransactionsResponse MUST have evidence field."""
        assert "evidence" in GovConTransactionsResponse.model_fields

    def test_transactions_response_default_version(self):
        """GovConTransactionsResponse MUST default govcon_version to CONTRACT_VERSION."""
        response = GovConTransactionsResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            allowable_count=0,
            unallowable_count=0,
            pending_review_count=0,
        )
        assert response.govcon_version == GOVCON_CONTRACT_VERSION

    def test_transactions_response_default_lifecycle(self):
        """GovConTransactionsResponse MUST default lifecycle to success."""
        response = GovConTransactionsResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            allowable_count=0,
            unallowable_count=0,
            pending_review_count=0,
        )
        assert response.lifecycle.status == "success"

    def test_transactions_response_version_in_serialized_output(self):
        """govcon_version MUST be present in serialized JSON output."""
        response = GovConTransactionsResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            allowable_count=0,
            unallowable_count=0,
            pending_review_count=0,
        )
        data = response.model_dump()
        assert "govcon_version" in data
        assert data["govcon_version"] == GOVCON_CONTRACT_VERSION

    def test_transactions_response_lifecycle_in_serialized_output(self):
        """lifecycle MUST be present in serialized JSON output."""
        response = GovConTransactionsResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            allowable_count=0,
            unallowable_count=0,
            pending_review_count=0,
        )
        data = response.model_dump()
        assert "lifecycle" in data
        assert "status" in data["lifecycle"]

    def test_transactions_response_evidence_in_serialized_output(self):
        """evidence MUST be present in serialized JSON output."""
        response = GovConTransactionsResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            allowable_count=0,
            unallowable_count=0,
            pending_review_count=0,
        )
        data = response.model_dump()
        assert "evidence" in data
        assert "documents" in data["evidence"]
        assert "sources" in data["evidence"]
        assert "coverage_window" in data["evidence"]
        assert "last_verified_at" in data["evidence"]
        assert "dcaa_compliant" in data["evidence"]


# =============================================================================
# EXPORT PREVIEW RESPONSE MODEL TESTS
# =============================================================================


class TestExportPreviewResponseModel:
    """Tests for ExportPreviewResponse Pydantic model."""

    def test_export_response_has_version_field(self):
        """ExportPreviewResponse MUST have govcon_version field."""
        assert "govcon_version" in ExportPreviewResponse.model_fields

    def test_export_response_has_lifecycle_field(self):
        """ExportPreviewResponse MUST have lifecycle field."""
        assert "lifecycle" in ExportPreviewResponse.model_fields

    def test_export_response_has_evidence_field(self):
        """ExportPreviewResponse MUST have evidence field."""
        assert "evidence" in ExportPreviewResponse.model_fields

    def test_export_response_default_version(self):
        """ExportPreviewResponse MUST default govcon_version to CONTRACT_VERSION."""
        response = ExportPreviewResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            preview=[],
            summary={},
            export_ready=True,
            blocking_issues=[],
            audit_event_id="audit_001",
        )
        assert response.govcon_version == GOVCON_CONTRACT_VERSION

    def test_export_response_default_lifecycle(self):
        """ExportPreviewResponse MUST default lifecycle to success."""
        response = ExportPreviewResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            preview=[],
            summary={},
            export_ready=True,
            blocking_issues=[],
            audit_event_id="audit_001",
        )
        assert response.lifecycle.status == "success"

    def test_export_response_version_in_serialized_output(self):
        """govcon_version MUST be present in serialized JSON output."""
        response = ExportPreviewResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            preview=[],
            summary={},
            export_ready=True,
            blocking_issues=[],
            audit_event_id="audit_001",
        )
        data = response.model_dump()
        assert "govcon_version" in data
        assert data["govcon_version"] == GOVCON_CONTRACT_VERSION


# =============================================================================
# ALL RESPONSES CONTRACT TEST
# =============================================================================


class TestAllGovConResponses:
    """Tests that ALL GovCon response types include required fields."""

    def test_all_response_models_have_version(self):
        """All GovCon response models MUST have govcon_version field."""
        response_models = [
            GovConTransactionsResponse,
            ExportPreviewResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "govcon_version" in field_names, (
                f"{model.__name__} MUST have govcon_version field"
            )

    def test_all_response_models_have_lifecycle(self):
        """All GovCon response models MUST have lifecycle field."""
        response_models = [
            GovConTransactionsResponse,
            ExportPreviewResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "lifecycle" in field_names, (
                f"{model.__name__} MUST have lifecycle field"
            )

    def test_all_response_models_have_evidence(self):
        """All GovCon response models MUST have evidence field."""
        response_models = [
            GovConTransactionsResponse,
            ExportPreviewResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "evidence" in field_names, (
                f"{model.__name__} MUST have evidence field"
            )


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestDeterministicBehavior:
    """Tests to ensure deterministic behavior (no randomness in contract)."""

    def test_govcon_version_is_stable(self):
        """govcon_version MUST be stable across multiple calls."""
        versions = [
            wrap_govcon_response(ok=True, sources=["test"])["govcon_version"]
            for _ in range(10)
        ]
        assert all(v == GOVCON_CONTRACT_VERSION for v in versions)

    def test_lifecycle_statuses_are_frozen(self):
        """VALID_GOVCON_LIFECYCLE_STATUSES MUST be immutable."""
        assert isinstance(VALID_GOVCON_LIFECYCLE_STATUSES, frozenset)

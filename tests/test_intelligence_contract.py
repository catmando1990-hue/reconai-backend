# tests/test_intelligence_contract.py
"""
CONTRACT TESTS for Intelligence API.

These tests LOCK the backend contract for Intelligence endpoints.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

All Intelligence responses MUST include:
- intelligence_version: int (ALWAYS present, value = 1)
- lifecycle: dict (ALWAYS present, status + reason_code)
- evidence: dict (ALWAYS present, metadata for auditability)
"""

import pytest
from app.guardrails.intelligence_contract import (
    INTELLIGENCE_CONTRACT_VERSION,
    VALID_LIFECYCLE_STATUSES,
    enforce_contract,
    wrap_intelligence_response,
    validate_intelligence_result,
    apply_confidence_gating,
    create_intelligence_lifecycle,
    create_evidence_metadata,
)
from app.intelligence.models import (
    ClassifyResponse,
    TransactionOverlayResponse,
    ClassificationResult,
    EvidenceItem,
    Lifecycle,
    EvidenceMetadata,
    CoverageWindow,
)


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


class TestIntelligenceContractVersion:
    """Tests for INTELLIGENCE_CONTRACT_VERSION constant."""

    def test_intelligence_version_is_integer(self):
        """INTELLIGENCE_CONTRACT_VERSION MUST be an integer."""
        assert isinstance(INTELLIGENCE_CONTRACT_VERSION, int)

    def test_intelligence_version_is_positive(self):
        """INTELLIGENCE_CONTRACT_VERSION MUST be positive."""
        assert INTELLIGENCE_CONTRACT_VERSION > 0

    def test_intelligence_version_current_value(self):
        """INTELLIGENCE_CONTRACT_VERSION MUST be 1 (current contract version)."""
        assert INTELLIGENCE_CONTRACT_VERSION == 1


# =============================================================================
# ENFORCE CONTRACT TESTS
# =============================================================================


class TestEnforceContract:
    """Tests for enforce_contract function."""

    def test_enforce_contract_includes_version(self):
        """enforce_contract MUST return intelligence_version."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test explanation",
                "evidence": [{"type": "test"}],
            }
        ]
        response = enforce_contract(results)
        assert "intelligence_version" in response
        assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION

    def test_enforce_contract_includes_lifecycle(self):
        """enforce_contract MUST return lifecycle."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test explanation",
                "evidence": [{"type": "test"}],
            }
        ]
        response = enforce_contract(results)
        assert "lifecycle" in response
        assert "status" in response["lifecycle"]
        assert response["lifecycle"]["status"] in VALID_LIFECYCLE_STATUSES

    def test_enforce_contract_includes_evidence(self):
        """enforce_contract MUST return evidence metadata."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test explanation",
                "evidence": [{"type": "test"}],
            }
        ]
        response = enforce_contract(results)
        assert "evidence" in response
        assert "sources" in response["evidence"]
        assert "coverage_window" in response["evidence"]
        assert "evaluated_at" in response["evidence"]
        assert "confidence_score" in response["evidence"]

    def test_enforce_contract_version_is_integer(self):
        """intelligence_version in enforce_contract MUST be integer."""
        results = []
        response = enforce_contract(results)
        assert isinstance(response["intelligence_version"], int)

    def test_enforce_contract_empty_results_has_version(self):
        """Even with empty results, intelligence_version MUST be present."""
        response = enforce_contract([])
        assert "intelligence_version" in response
        assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION

    def test_enforce_contract_empty_results_has_lifecycle(self):
        """Empty results MUST have lifecycle with no_data status."""
        response = enforce_contract([])
        assert "lifecycle" in response
        assert response["lifecycle"]["status"] == "no_data"
        assert response["lifecycle"]["reason_code"] == "NO_INPUT_RESULTS"

    def test_enforce_contract_empty_results_has_evidence(self):
        """Empty results MUST have evidence metadata."""
        response = enforce_contract([])
        assert "evidence" in response
        assert "sources" in response["evidence"]
        assert "evaluated_at" in response["evidence"]


# =============================================================================
# WRAP INTELLIGENCE RESPONSE TESTS
# =============================================================================


class TestWrapIntelligenceResponse:
    """Tests for wrap_intelligence_response function."""

    def test_wrap_response_includes_version(self):
        """wrap_intelligence_response MUST return intelligence_version."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test",
                "evidence": [],
            }
        ]
        response = wrap_intelligence_response(results)
        assert "intelligence_version" in response
        assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION

    def test_wrap_response_includes_lifecycle(self):
        """wrap_intelligence_response MUST return lifecycle."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test",
                "evidence": [],
            }
        ]
        response = wrap_intelligence_response(results)
        assert "lifecycle" in response
        assert response["lifecycle"]["status"] == "success"

    def test_wrap_response_includes_evidence(self):
        """wrap_intelligence_response MUST return evidence metadata."""
        results = [
            {
                "confidence": 0.9,
                "explanation": "Test",
                "evidence": [],
            }
        ]
        response = wrap_intelligence_response(results)
        assert "evidence" in response
        assert "sources" in response["evidence"]
        assert "evaluated_at" in response["evidence"]

    def test_wrap_response_version_is_integer(self):
        """intelligence_version in wrap_intelligence_response MUST be integer."""
        response = wrap_intelligence_response([])
        assert isinstance(response["intelligence_version"], int)

    def test_wrap_response_with_extra_fields_preserves_version(self):
        """Extra fields MUST not override intelligence_version."""
        response = wrap_intelligence_response(
            [], result_key="items", timestamp="2024-01-01T00:00:00Z"
        )
        assert "intelligence_version" in response
        assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
        assert response["timestamp"] == "2024-01-01T00:00:00Z"

    def test_wrap_response_with_extra_fields_preserves_lifecycle(self):
        """Extra fields MUST not override lifecycle."""
        response = wrap_intelligence_response(
            [], result_key="items", timestamp="2024-01-01T00:00:00Z"
        )
        assert "lifecycle" in response
        assert response["lifecycle"]["status"] == "no_data"


# =============================================================================
# CLASSIFY RESPONSE MODEL TESTS
# =============================================================================


def _make_classification():
    """Helper to create a valid classification for testing."""
    return ClassificationResult(
        transaction_id="tx_001",
        category="business_expense",
        confidence=0.9,
        explanation="Test",
        evidence=[
            EvidenceItem(
                evidence_type="merchant_pattern",
                value="test",
                weight=0.5,
                description="Test evidence",
            )
        ],
        requires_review=False,
        classified_at="2024-01-01T00:00:00Z",
    )


class TestClassifyResponseModel:
    """Tests for ClassifyResponse Pydantic model."""

    def test_classify_response_has_version_field(self):
        """ClassifyResponse MUST have intelligence_version field."""
        assert "intelligence_version" in ClassifyResponse.model_fields

    def test_classify_response_has_lifecycle_field(self):
        """ClassifyResponse MUST have lifecycle field."""
        assert "lifecycle" in ClassifyResponse.model_fields

    def test_classify_response_has_evidence_field(self):
        """ClassifyResponse MUST have evidence field."""
        assert "evidence" in ClassifyResponse.model_fields

    def test_classify_response_default_version(self):
        """ClassifyResponse MUST default intelligence_version to CONTRACT_VERSION."""
        response = ClassifyResponse(
            ok=True,
            request_id="test_123",
            classified_at="2024-01-01T00:00:00Z",
            classifications=[_make_classification()],
            duplicates=[],
            total_processed=1,
            flagged_for_review=0,
            audit_event_id="audit_001",
        )
        assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION

    def test_classify_response_default_lifecycle(self):
        """ClassifyResponse MUST default lifecycle to success."""
        response = ClassifyResponse(
            ok=True,
            request_id="test_123",
            classified_at="2024-01-01T00:00:00Z",
            classifications=[],
            duplicates=[],
            total_processed=0,
            flagged_for_review=0,
            audit_event_id="audit_001",
        )
        assert response.lifecycle.status == "success"

    def test_classify_response_version_in_serialized_output(self):
        """intelligence_version MUST be present in serialized JSON output."""
        response = ClassifyResponse(
            ok=True,
            request_id="test_123",
            classified_at="2024-01-01T00:00:00Z",
            classifications=[],
            duplicates=[],
            total_processed=0,
            flagged_for_review=0,
            audit_event_id="audit_001",
        )
        data = response.model_dump()
        assert "intelligence_version" in data
        assert data["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION

    def test_classify_response_lifecycle_in_serialized_output(self):
        """lifecycle MUST be present in serialized JSON output."""
        response = ClassifyResponse(
            ok=True,
            request_id="test_123",
            classified_at="2024-01-01T00:00:00Z",
            classifications=[],
            duplicates=[],
            total_processed=0,
            flagged_for_review=0,
            audit_event_id="audit_001",
        )
        data = response.model_dump()
        assert "lifecycle" in data
        assert "status" in data["lifecycle"]

    def test_classify_response_evidence_in_serialized_output(self):
        """evidence MUST be present in serialized JSON output."""
        response = ClassifyResponse(
            ok=True,
            request_id="test_123",
            classified_at="2024-01-01T00:00:00Z",
            classifications=[],
            duplicates=[],
            total_processed=0,
            flagged_for_review=0,
            audit_event_id="audit_001",
        )
        data = response.model_dump()
        assert "evidence" in data
        assert "sources" in data["evidence"]
        assert "evaluated_at" in data["evidence"]


# =============================================================================
# TRANSACTION OVERLAY RESPONSE MODEL TESTS
# =============================================================================


class TestTransactionOverlayResponseModel:
    """Tests for TransactionOverlayResponse Pydantic model."""

    def test_overlay_response_has_version_field(self):
        """TransactionOverlayResponse MUST have intelligence_version field."""
        assert "intelligence_version" in TransactionOverlayResponse.model_fields

    def test_overlay_response_has_lifecycle_field(self):
        """TransactionOverlayResponse MUST have lifecycle field."""
        assert "lifecycle" in TransactionOverlayResponse.model_fields

    def test_overlay_response_has_evidence_field(self):
        """TransactionOverlayResponse MUST have evidence field."""
        assert "evidence" in TransactionOverlayResponse.model_fields

    def test_overlay_response_default_version(self):
        """TransactionOverlayResponse MUST default intelligence_version to CONTRACT_VERSION."""
        response = TransactionOverlayResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            unclassified_count=0,
            flagged_count=0,
        )
        assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION

    def test_overlay_response_default_lifecycle(self):
        """TransactionOverlayResponse MUST default lifecycle to success."""
        response = TransactionOverlayResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            unclassified_count=0,
            flagged_count=0,
        )
        assert response.lifecycle.status == "success"

    def test_overlay_response_version_in_serialized_output(self):
        """intelligence_version MUST be present in serialized JSON output."""
        response = TransactionOverlayResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            unclassified_count=0,
            flagged_count=0,
        )
        data = response.model_dump()
        assert "intelligence_version" in data
        assert data["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION

    def test_overlay_response_lifecycle_in_serialized_output(self):
        """lifecycle MUST be present in serialized JSON output."""
        response = TransactionOverlayResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            unclassified_count=0,
            flagged_count=0,
        )
        data = response.model_dump()
        assert "lifecycle" in data
        assert "status" in data["lifecycle"]

    def test_overlay_response_evidence_in_serialized_output(self):
        """evidence MUST be present in serialized JSON output."""
        response = TransactionOverlayResponse(
            ok=True,
            request_id="test_123",
            generated_at="2024-01-01T00:00:00Z",
            transactions=[],
            total_count=0,
            classified_count=0,
            unclassified_count=0,
            flagged_count=0,
        )
        data = response.model_dump()
        assert "evidence" in data
        assert "sources" in data["evidence"]
        assert "evaluated_at" in data["evidence"]


# =============================================================================
# ALL RESPONSES CONTRACT TEST
# =============================================================================


class TestAllIntelligenceResponses:
    """Tests that ALL Intelligence response types include required fields."""

    def test_all_response_models_have_version(self):
        """All Intelligence response models MUST have intelligence_version field."""
        response_models = [
            ClassifyResponse,
            TransactionOverlayResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "intelligence_version" in field_names, (
                f"{model.__name__} MUST have intelligence_version field"
            )

    def test_all_response_models_have_lifecycle(self):
        """All Intelligence response models MUST have lifecycle field."""
        response_models = [
            ClassifyResponse,
            TransactionOverlayResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "lifecycle" in field_names, (
                f"{model.__name__} MUST have lifecycle field"
            )

    def test_all_response_models_have_evidence(self):
        """All Intelligence response models MUST have evidence field."""
        response_models = [
            ClassifyResponse,
            TransactionOverlayResponse,
        ]

        for model in response_models:
            field_names = model.model_fields.keys()
            assert "evidence" in field_names, (
                f"{model.__name__} MUST have evidence field"
            )


# =============================================================================
# LIFECYCLE VALIDATION TESTS
# =============================================================================


class TestLifecycleValidation:
    """Tests for lifecycle validation logic."""

    def test_lifecycle_requires_reason_code_for_non_success(self):
        """reason_code MUST be present when status != success."""
        with pytest.raises(ValueError, match="reason_code is required"):
            create_intelligence_lifecycle("partial")

    def test_lifecycle_clears_reason_code_for_success(self):
        """reason_code MUST be None for success status."""
        lifecycle = create_intelligence_lifecycle("success", "SHOULD_BE_CLEARED")
        assert lifecycle["reason_code"] is None

    def test_lifecycle_rejects_invalid_status(self):
        """Invalid status values MUST be rejected."""
        with pytest.raises(ValueError, match="Invalid lifecycle status"):
            create_intelligence_lifecycle("invalid_status")

    def test_lifecycle_accepts_all_valid_statuses(self):
        """All valid statuses MUST be accepted."""
        for status in ["success", "partial", "failed", "no_data"]:
            if status == "success":
                lifecycle = create_intelligence_lifecycle(status)
            else:
                lifecycle = create_intelligence_lifecycle(status, "TEST_REASON")
            assert lifecycle["status"] == status


class TestEvidenceMetadataValidation:
    """Tests for evidence metadata validation logic."""

    def test_evidence_rejects_invalid_confidence(self):
        """Invalid confidence_score values MUST be rejected."""
        with pytest.raises(ValueError, match="confidence_score must be between"):
            create_evidence_metadata(["test"], confidence_score=1.5)

    def test_evidence_rejects_negative_confidence(self):
        """Negative confidence_score values MUST be rejected."""
        with pytest.raises(ValueError, match="confidence_score must be between"):
            create_evidence_metadata(["test"], confidence_score=-0.1)

    def test_evidence_accepts_valid_confidence(self):
        """Valid confidence_score values MUST be accepted."""
        for score in [0.0, 0.5, 0.85, 1.0]:
            evidence = create_evidence_metadata(["test"], confidence_score=score)
            assert evidence["confidence_score"] == score


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


class TestDeterministicBehavior:
    """Tests to ensure deterministic behavior (no randomness in contract)."""

    def test_intelligence_version_is_stable(self):
        """intelligence_version MUST be stable across multiple calls."""
        versions = [
            enforce_contract([])["intelligence_version"] for _ in range(10)
        ]
        assert all(v == INTELLIGENCE_CONTRACT_VERSION for v in versions)

    def test_wrap_response_version_is_stable(self):
        """intelligence_version from wrap_intelligence_response MUST be stable."""
        versions = [
            wrap_intelligence_response([])["intelligence_version"] for _ in range(10)
        ]
        assert all(v == INTELLIGENCE_CONTRACT_VERSION for v in versions)

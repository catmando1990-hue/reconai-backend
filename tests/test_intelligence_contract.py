# tests/test_intelligence_contract.py
"""
CONTRACT TESTS for Intelligence API.

These tests LOCK the backend contract for Intelligence endpoints.
Any failure indicates schema drift and MUST be resolved before deployment.

CONTRACT VERSION: 1

All Intelligence responses MUST include:
- intelligence_version: int (ALWAYS present, value = 1)
"""

import pytest
from app.guardrails.intelligence_contract import (
    INTELLIGENCE_CONTRACT_VERSION,
    enforce_contract,
    wrap_intelligence_response,
    validate_intelligence_result,
    apply_confidence_gating,
)
from app.intelligence.models import (
    ClassifyResponse,
    TransactionOverlayResponse,
    ClassificationResult,
    EvidenceItem,
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


# =============================================================================
# TRANSACTION OVERLAY RESPONSE MODEL TESTS
# =============================================================================


class TestTransactionOverlayResponseModel:
    """Tests for TransactionOverlayResponse Pydantic model."""

    def test_overlay_response_has_version_field(self):
        """TransactionOverlayResponse MUST have intelligence_version field."""
        assert "intelligence_version" in TransactionOverlayResponse.model_fields

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


# =============================================================================
# ALL RESPONSES CONTRACT TEST
# =============================================================================


class TestAllIntelligenceResponses:
    """Tests that ALL Intelligence response types include intelligence_version."""

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

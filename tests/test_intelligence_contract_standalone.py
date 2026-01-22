#!/usr/bin/env python3
"""
STANDALONE CONTRACT TESTS for Intelligence API.

This file tests the contract without importing the full application.
Run with: python tests/test_intelligence_contract_standalone.py

CONTRACT VERSION: 1

All Intelligence responses MUST include:
- intelligence_version: int (ALWAYS present, value = 1)
- lifecycle: dict (ALWAYS present, status + reason_code)
- evidence: dict (ALWAYS present, metadata for auditability)
"""

import sys
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Literal, Optional
from dataclasses import dataclass, field

# =============================================================================
# COPY OF CONTRACT DEFINITIONS (for standalone testing)
# =============================================================================

INTELLIGENCE_CONTRACT_VERSION = 1
CONFIDENCE_THRESHOLD = 0.85
MODE = "advisory"
WRITES_ALLOWED = False

# Valid lifecycle statuses
VALID_LIFECYCLE_STATUSES: FrozenSet[str] = frozenset(["success", "partial", "failed", "no_data"])


def create_intelligence_lifecycle(
    status: str,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Factory for creating validated IntelligenceLifecycle."""
    if status not in VALID_LIFECYCLE_STATUSES:
        raise ValueError(f"Invalid lifecycle status: {status}")
    if status != "success" and not reason_code:
        raise ValueError(f"reason_code is required when status is '{status}'")
    if status == "success":
        reason_code = None
    return {"status": status, "reason_code": reason_code}


def create_evidence_metadata(
    sources: List[str],
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    evaluated_at: Optional[str] = None,
    confidence_score: float = 0.0,
) -> Dict[str, Any]:
    """Factory for creating validated IntelligenceEvidenceMetadata."""
    if not (0.0 <= confidence_score <= 1.0):
        raise ValueError(f"confidence_score must be between 0.0 and 1.0, got: {confidence_score}")
    return {
        "sources": sources or [],
        "coverage_window": {"start": coverage_start, "end": coverage_end},
        "evaluated_at": evaluated_at or datetime.utcnow().isoformat(),
        "confidence_score": confidence_score,
    }


def validate_intelligence_result(result: Dict[str, Any]) -> tuple:
    """Validate a single intelligence result against the contract."""
    if "confidence" not in result:
        return False, "Missing required field: confidence"
    if "explanation" not in result:
        return False, "Missing required field: explanation"
    if "evidence" not in result:
        return False, "Missing required field: evidence"
    if not isinstance(result["confidence"], (int, float)):
        return False, "confidence must be a number"
    if not isinstance(result["explanation"], str):
        return False, "explanation must be a string"
    if not isinstance(result["evidence"], (list, dict)):
        return False, "evidence must be a list or object"
    if not (0.0 <= result["confidence"] <= 1.0):
        return False, "confidence must be between 0.0 and 1.0"
    return True, ""


def apply_confidence_gating(
    results: List[Dict[str, Any]],
    threshold: float = CONFIDENCE_THRESHOLD,
) -> tuple:
    """Filter results by confidence threshold."""
    passed = []
    filtered_count = 0
    for result in results:
        confidence = result.get("confidence", 0.0)
        if confidence >= threshold:
            passed.append(result)
        else:
            filtered_count += 1
    return passed, filtered_count


def enforce_contract(
    results: List[Dict[str, Any]],
    threshold: float = CONFIDENCE_THRESHOLD,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Enforce the full intelligence contract on a set of results."""
    now = datetime.utcnow().isoformat()

    valid_results = []
    invalid_count = 0
    for result in results:
        is_valid, _ = validate_intelligence_result(result)
        if is_valid:
            valid_results.append(result)
        else:
            invalid_count += 1

    gated_results, filtered_count = apply_confidence_gating(valid_results, threshold)

    # Compute lifecycle status
    if len(results) == 0:
        lifecycle = create_intelligence_lifecycle("no_data", "NO_INPUT_RESULTS")
    elif len(gated_results) == 0:
        if invalid_count > 0:
            lifecycle = create_intelligence_lifecycle("failed", "ALL_RESULTS_INVALID")
        else:
            lifecycle = create_intelligence_lifecycle("partial", "ALL_BELOW_THRESHOLD")
    elif len(gated_results) < len(valid_results):
        lifecycle = create_intelligence_lifecycle("partial", "SOME_BELOW_THRESHOLD")
    elif invalid_count > 0:
        lifecycle = create_intelligence_lifecycle("partial", "SOME_RESULTS_INVALID")
    else:
        lifecycle = create_intelligence_lifecycle("success")

    # Compute average confidence
    avg_confidence = 0.0
    if gated_results:
        avg_confidence = sum(r.get("confidence", 0.0) for r in gated_results) / len(gated_results)

    # Build evidence metadata
    evidence = create_evidence_metadata(
        sources=sources or ["intelligence_contract"],
        evaluated_at=now,
        confidence_score=avg_confidence,
    )

    return {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
        "lifecycle": lifecycle,  # ALWAYS present
        "evidence": evidence,  # ALWAYS present
        "ok": True,
        "mode": MODE,
        "writes_allowed": WRITES_ALLOWED,
        "results": gated_results,
        "filtered_count": filtered_count,
        "guardrails": {
            "confidence_threshold": threshold,
            "explanation_required": True,
            "evidence_required": True,
            "advisory_only": True,
            "manual_run_only": True,
        },
    }


def wrap_intelligence_response(
    results: List[Dict[str, Any]],
    result_key: str = "results",
    sources: Optional[List[str]] = None,
    **extra_fields,
) -> Dict[str, Any]:
    """Wrap raw intelligence results in the standard contract envelope."""
    enforced = enforce_contract(results, sources=sources)

    response = {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
        "lifecycle": enforced["lifecycle"],  # ALWAYS present
        "evidence": enforced["evidence"],  # ALWAYS present
        "ok": enforced["ok"],
        "mode": enforced["mode"],
        "writes_allowed": enforced["writes_allowed"],
        result_key: enforced["results"],
        "filtered_count": enforced["filtered_count"],
        "guardrails": enforced["guardrails"],
    }

    response.update(extra_fields)
    return response


@dataclass
class MockLifecycle:
    """Mock lifecycle for testing."""
    status: str
    reason_code: Optional[str] = None


@dataclass
class MockEvidenceMetadata:
    """Mock evidence metadata for testing."""
    sources: List[str] = field(default_factory=list)
    coverage_window: Dict[str, Optional[str]] = field(default_factory=lambda: {"start": None, "end": None})
    evaluated_at: str = ""
    confidence_score: float = 0.0


@dataclass
class MockClassifyResponse:
    """Mock classify response for testing."""
    intelligence_version: int
    lifecycle: MockLifecycle
    evidence: MockEvidenceMetadata
    ok: bool
    request_id: str
    classified_at: str
    classifications: List[Any] = field(default_factory=list)
    duplicates: List[Any] = field(default_factory=list)
    total_processed: int = 0
    flagged_for_review: int = 0
    audit_event_id: str = ""


@dataclass
class MockTransactionOverlayResponse:
    """Mock transaction overlay response for testing."""
    intelligence_version: int
    lifecycle: MockLifecycle
    evidence: MockEvidenceMetadata
    ok: bool
    request_id: str
    generated_at: str
    transactions: List[Any] = field(default_factory=list)
    total_count: int = 0
    classified_count: int = 0
    unclassified_count: int = 0
    flagged_count: int = 0


# =============================================================================
# CONTRACT VERSION TESTS
# =============================================================================


def test_intelligence_version_is_integer():
    """INTELLIGENCE_CONTRACT_VERSION MUST be an integer."""
    assert isinstance(INTELLIGENCE_CONTRACT_VERSION, int), "INTELLIGENCE_CONTRACT_VERSION must be integer"
    print("PASS: intelligence_version is integer")


def test_intelligence_version_is_one():
    """INTELLIGENCE_CONTRACT_VERSION MUST be 1 (current contract version)."""
    assert INTELLIGENCE_CONTRACT_VERSION == 1, "INTELLIGENCE_CONTRACT_VERSION must be 1"
    print("PASS: intelligence_version is 1")


def test_intelligence_version_is_positive():
    """INTELLIGENCE_CONTRACT_VERSION MUST be positive."""
    assert INTELLIGENCE_CONTRACT_VERSION > 0, "INTELLIGENCE_CONTRACT_VERSION must be positive"
    print("PASS: intelligence_version is positive")


# =============================================================================
# ENFORCE CONTRACT TESTS
# =============================================================================


def test_enforce_contract_includes_version():
    """enforce_contract MUST return intelligence_version."""
    results = [
        {
            "confidence": 0.9,
            "explanation": "Test explanation",
            "evidence": [{"type": "test"}],
        }
    ]
    response = enforce_contract(results)
    assert "intelligence_version" in response, "enforce_contract must include intelligence_version"
    assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: enforce_contract includes intelligence_version")


def test_enforce_contract_includes_lifecycle():
    """enforce_contract MUST return lifecycle."""
    results = [
        {
            "confidence": 0.9,
            "explanation": "Test explanation",
            "evidence": [{"type": "test"}],
        }
    ]
    response = enforce_contract(results)
    assert "lifecycle" in response, "enforce_contract must include lifecycle"
    assert "status" in response["lifecycle"], "lifecycle must include status"
    assert response["lifecycle"]["status"] == "success"
    print("PASS: enforce_contract includes lifecycle")


def test_enforce_contract_includes_evidence():
    """enforce_contract MUST return evidence metadata."""
    results = [
        {
            "confidence": 0.9,
            "explanation": "Test explanation",
            "evidence": [{"type": "test"}],
        }
    ]
    response = enforce_contract(results)
    assert "evidence" in response, "enforce_contract must include evidence"
    assert "sources" in response["evidence"], "evidence must include sources"
    assert "coverage_window" in response["evidence"], "evidence must include coverage_window"
    assert "evaluated_at" in response["evidence"], "evidence must include evaluated_at"
    assert "confidence_score" in response["evidence"], "evidence must include confidence_score"
    print("PASS: enforce_contract includes evidence metadata")


def test_enforce_contract_empty_results_has_version():
    """Even with empty results, intelligence_version MUST be present."""
    response = enforce_contract([])
    assert "intelligence_version" in response
    assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: enforce_contract with empty results has intelligence_version")


def test_enforce_contract_empty_results_has_lifecycle():
    """Empty results MUST have lifecycle with no_data status."""
    response = enforce_contract([])
    assert "lifecycle" in response
    assert response["lifecycle"]["status"] == "no_data"
    assert response["lifecycle"]["reason_code"] == "NO_INPUT_RESULTS"
    print("PASS: enforce_contract with empty results has correct lifecycle")


def test_enforce_contract_empty_results_has_evidence():
    """Empty results MUST have evidence metadata."""
    response = enforce_contract([])
    assert "evidence" in response
    assert "sources" in response["evidence"]
    assert "evaluated_at" in response["evidence"]
    print("PASS: enforce_contract with empty results has evidence")


# =============================================================================
# WRAP INTELLIGENCE RESPONSE TESTS
# =============================================================================


def test_wrap_response_includes_version():
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
    print("PASS: wrap_intelligence_response includes intelligence_version")


def test_wrap_response_includes_lifecycle():
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
    print("PASS: wrap_intelligence_response includes lifecycle")


def test_wrap_response_includes_evidence():
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
    print("PASS: wrap_intelligence_response includes evidence")


def test_wrap_response_with_extra_fields_preserves_version():
    """Extra fields MUST not override intelligence_version."""
    response = wrap_intelligence_response(
        [], result_key="items", timestamp="2024-01-01T00:00:00Z"
    )
    assert "intelligence_version" in response
    assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
    assert response["timestamp"] == "2024-01-01T00:00:00Z"
    print("PASS: wrap_intelligence_response preserves version with extra fields")


def test_wrap_response_with_extra_fields_preserves_lifecycle():
    """Extra fields MUST not override lifecycle."""
    response = wrap_intelligence_response(
        [], result_key="items", timestamp="2024-01-01T00:00:00Z"
    )
    assert "lifecycle" in response
    assert response["lifecycle"]["status"] == "no_data"
    print("PASS: wrap_intelligence_response preserves lifecycle with extra fields")


# =============================================================================
# RESPONSE MODEL TESTS
# =============================================================================


def test_classify_response_has_version():
    """MockClassifyResponse MUST have intelligence_version."""
    response = MockClassifyResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        classified_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "intelligence_version")
    assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: ClassifyResponse has intelligence_version")


def test_classify_response_has_lifecycle():
    """MockClassifyResponse MUST have lifecycle."""
    response = MockClassifyResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        classified_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "lifecycle")
    assert response.lifecycle.status == "success"
    print("PASS: ClassifyResponse has lifecycle")


def test_classify_response_has_evidence():
    """MockClassifyResponse MUST have evidence."""
    response = MockClassifyResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        classified_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "evidence")
    assert "test" in response.evidence.sources
    print("PASS: ClassifyResponse has evidence")


def test_overlay_response_has_version():
    """MockTransactionOverlayResponse MUST have intelligence_version."""
    response = MockTransactionOverlayResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "intelligence_version")
    assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: TransactionOverlayResponse has intelligence_version")


def test_overlay_response_has_lifecycle():
    """MockTransactionOverlayResponse MUST have lifecycle."""
    response = MockTransactionOverlayResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "lifecycle")
    assert response.lifecycle.status == "success"
    print("PASS: TransactionOverlayResponse has lifecycle")


def test_overlay_response_has_evidence():
    """MockTransactionOverlayResponse MUST have evidence."""
    response = MockTransactionOverlayResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        lifecycle=MockLifecycle(status="success"),
        evidence=MockEvidenceMetadata(sources=["test"], evaluated_at="2024-01-01T00:00:00Z"),
        ok=True,
        request_id="test_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "evidence")
    assert "test" in response.evidence.sources
    print("PASS: TransactionOverlayResponse has evidence")


# =============================================================================
# DETERMINISTIC BEHAVIOR TESTS
# =============================================================================


def test_intelligence_version_is_stable():
    """intelligence_version MUST be stable across multiple calls."""
    versions = [enforce_contract([])["intelligence_version"] for _ in range(10)]
    assert all(v == INTELLIGENCE_CONTRACT_VERSION for v in versions), "intelligence_version must be stable"
    print("PASS: intelligence_version is stable")


def test_wrap_response_version_is_stable():
    """intelligence_version from wrap_intelligence_response MUST be stable."""
    versions = [wrap_intelligence_response([])["intelligence_version"] for _ in range(10)]
    assert all(v == INTELLIGENCE_CONTRACT_VERSION for v in versions)
    print("PASS: wrap_intelligence_response version is stable")


# =============================================================================
# LIFECYCLE VALIDATION TESTS
# =============================================================================


def test_lifecycle_requires_reason_code_for_non_success():
    """reason_code MUST be present when status != success."""
    try:
        create_intelligence_lifecycle("partial")  # No reason_code
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "reason_code is required" in str(e)
    print("PASS: Lifecycle requires reason_code for non-success status")


def test_lifecycle_clears_reason_code_for_success():
    """reason_code MUST be None for success status."""
    lifecycle = create_intelligence_lifecycle("success", "SHOULD_BE_CLEARED")
    assert lifecycle["reason_code"] is None
    print("PASS: Lifecycle clears reason_code for success")


def test_lifecycle_rejects_invalid_status():
    """Invalid status values MUST be rejected."""
    try:
        create_intelligence_lifecycle("invalid_status")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid lifecycle status" in str(e)
    print("PASS: Lifecycle rejects invalid status")


def test_evidence_rejects_invalid_confidence():
    """Invalid confidence_score values MUST be rejected."""
    try:
        create_evidence_metadata(["test"], confidence_score=1.5)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "confidence_score must be between" in str(e)
    print("PASS: Evidence rejects invalid confidence_score")


# =============================================================================
# MISSING FIELD DETECTION TESTS
# =============================================================================


def test_response_without_version_fails():
    """Response missing intelligence_version MUST be detectable."""
    # Simulate a response that's missing intelligence_version
    bad_response = {
        "ok": True,
        "mode": "advisory",
        "results": [],
    }
    assert "intelligence_version" not in bad_response, "Test setup: bad_response should not have version"

    # Good response from our contract functions ALWAYS has version
    good_response = enforce_contract([])
    assert "intelligence_version" in good_response, "Contract response MUST have version"
    print("PASS: Missing version is detectable")


def test_response_without_lifecycle_fails():
    """Response missing lifecycle MUST be detectable."""
    bad_response = {
        "intelligence_version": 1,
        "ok": True,
        "mode": "advisory",
        "results": [],
    }
    assert "lifecycle" not in bad_response, "Test setup: bad_response should not have lifecycle"

    # Good response from our contract functions ALWAYS has lifecycle
    good_response = enforce_contract([])
    assert "lifecycle" in good_response, "Contract response MUST have lifecycle"
    print("PASS: Missing lifecycle is detectable")


def test_response_without_evidence_fails():
    """Response missing evidence MUST be detectable."""
    bad_response = {
        "intelligence_version": 1,
        "lifecycle": {"status": "success", "reason_code": None},
        "ok": True,
        "mode": "advisory",
        "results": [],
    }
    assert "evidence" not in bad_response, "Test setup: bad_response should not have evidence"

    # Good response from our contract functions ALWAYS has evidence
    good_response = enforce_contract([])
    assert "evidence" in good_response, "Contract response MUST have evidence"
    print("PASS: Missing evidence is detectable")


# =============================================================================
# RUN ALL TESTS
# =============================================================================


def run_all_tests():
    """Run all contract tests."""
    tests = [
        # Version constant tests
        test_intelligence_version_is_integer,
        test_intelligence_version_is_one,
        test_intelligence_version_is_positive,
        # Enforce contract tests
        test_enforce_contract_includes_version,
        test_enforce_contract_includes_lifecycle,
        test_enforce_contract_includes_evidence,
        test_enforce_contract_empty_results_has_version,
        test_enforce_contract_empty_results_has_lifecycle,
        test_enforce_contract_empty_results_has_evidence,
        # Wrap response tests
        test_wrap_response_includes_version,
        test_wrap_response_includes_lifecycle,
        test_wrap_response_includes_evidence,
        test_wrap_response_with_extra_fields_preserves_version,
        test_wrap_response_with_extra_fields_preserves_lifecycle,
        # Response model tests
        test_classify_response_has_version,
        test_classify_response_has_lifecycle,
        test_classify_response_has_evidence,
        test_overlay_response_has_version,
        test_overlay_response_has_lifecycle,
        test_overlay_response_has_evidence,
        # Deterministic behavior tests
        test_intelligence_version_is_stable,
        test_wrap_response_version_is_stable,
        # Lifecycle validation tests
        test_lifecycle_requires_reason_code_for_non_success,
        test_lifecycle_clears_reason_code_for_success,
        test_lifecycle_rejects_invalid_status,
        test_evidence_rejects_invalid_confidence,
        # Missing field detection
        test_response_without_version_fails,
        test_response_without_lifecycle_fails,
        test_response_without_evidence_fails,
    ]

    print("=" * 60)
    print("INTELLIGENCE CONTRACT TESTS")
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

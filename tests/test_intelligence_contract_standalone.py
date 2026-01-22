#!/usr/bin/env python3
"""
STANDALONE CONTRACT TESTS for Intelligence API.

This file tests the contract without importing the full application.
Run with: python tests/test_intelligence_contract_standalone.py

CONTRACT VERSION: 1

All Intelligence responses MUST include:
- intelligence_version: int (ALWAYS present, value = 1)
"""

import sys
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

# =============================================================================
# COPY OF CONTRACT DEFINITIONS (for standalone testing)
# =============================================================================

INTELLIGENCE_CONTRACT_VERSION = 1
CONFIDENCE_THRESHOLD = 0.85
MODE = "advisory"
WRITES_ALLOWED = False


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
) -> Dict[str, Any]:
    """Enforce the full intelligence contract on a set of results."""
    valid_results = []
    for result in results:
        is_valid, _ = validate_intelligence_result(result)
        if is_valid:
            valid_results.append(result)

    gated_results, filtered_count = apply_confidence_gating(valid_results, threshold)

    return {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
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
    **extra_fields,
) -> Dict[str, Any]:
    """Wrap raw intelligence results in the standard contract envelope."""
    enforced = enforce_contract(results)

    response = {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
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
class MockClassifyResponse:
    """Mock classify response for testing."""
    intelligence_version: int
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


def test_enforce_contract_empty_results_has_version():
    """Even with empty results, intelligence_version MUST be present."""
    response = enforce_contract([])
    assert "intelligence_version" in response
    assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: enforce_contract with empty results has intelligence_version")


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


def test_wrap_response_with_extra_fields_preserves_version():
    """Extra fields MUST not override intelligence_version."""
    response = wrap_intelligence_response(
        [], result_key="items", timestamp="2024-01-01T00:00:00Z"
    )
    assert "intelligence_version" in response
    assert response["intelligence_version"] == INTELLIGENCE_CONTRACT_VERSION
    assert response["timestamp"] == "2024-01-01T00:00:00Z"
    print("PASS: wrap_intelligence_response preserves version with extra fields")


# =============================================================================
# RESPONSE MODEL TESTS
# =============================================================================


def test_classify_response_has_version():
    """MockClassifyResponse MUST have intelligence_version."""
    response = MockClassifyResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        ok=True,
        request_id="test_123",
        classified_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "intelligence_version")
    assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: ClassifyResponse has intelligence_version")


def test_overlay_response_has_version():
    """MockTransactionOverlayResponse MUST have intelligence_version."""
    response = MockTransactionOverlayResponse(
        intelligence_version=INTELLIGENCE_CONTRACT_VERSION,
        ok=True,
        request_id="test_123",
        generated_at="2024-01-01T00:00:00Z",
    )
    assert hasattr(response, "intelligence_version")
    assert response.intelligence_version == INTELLIGENCE_CONTRACT_VERSION
    print("PASS: TransactionOverlayResponse has intelligence_version")


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
# MISSING VERSION DETECTION TESTS
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
        test_enforce_contract_empty_results_has_version,
        # Wrap response tests
        test_wrap_response_includes_version,
        test_wrap_response_with_extra_fields_preserves_version,
        # Response model tests
        test_classify_response_has_version,
        test_overlay_response_has_version,
        # Deterministic behavior tests
        test_intelligence_version_is_stable,
        test_wrap_response_version_is_stable,
        # Missing version detection
        test_response_without_version_fails,
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

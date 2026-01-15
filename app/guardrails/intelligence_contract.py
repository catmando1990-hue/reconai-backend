# app/guardrails/intelligence_contract.py
"""
Intelligence Contract Enforcement (STEP 3)

Enforces Canonical AI Laws:
1. Advisory-only (read-only, no writes, no auto-exec)
2. Manual-run only (no background or implicit calls)
3. Confidence gating: surface results ONLY if confidence >= 0.85
4. Mandatory response schema: {confidence, explanation, evidence}
5. Block or downgrade responses that fail schema or confidence
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
from fastapi import HTTPException


# Contract constants
CONFIDENCE_THRESHOLD = 0.85
MODE = "advisory"
WRITES_ALLOWED = False


class IntelligenceResult(TypedDict, total=False):
    """Required schema for all intelligence results."""
    confidence: float
    explanation: str
    evidence: List[Any]


class IntelligenceResponse(TypedDict):
    """Standard intelligence response envelope."""
    ok: bool
    mode: str
    writes_allowed: bool
    results: List[IntelligenceResult]
    filtered_count: int
    guardrails: Dict[str, Any]


def validate_intelligence_result(result: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate a single intelligence result against the contract.

    Returns:
        (is_valid, error_message)
    """
    # Check required fields
    if "confidence" not in result:
        return False, "Missing required field: confidence"

    if "explanation" not in result:
        return False, "Missing required field: explanation"

    if "evidence" not in result:
        return False, "Missing required field: evidence"

    # Validate types
    if not isinstance(result["confidence"], (int, float)):
        return False, "confidence must be a number"

    if not isinstance(result["explanation"], str):
        return False, "explanation must be a string"

    if not isinstance(result["evidence"], (list, dict)):
        return False, "evidence must be a list or object"

    # Validate confidence range
    if not (0.0 <= result["confidence"] <= 1.0):
        return False, "confidence must be between 0.0 and 1.0"

    return True, ""


def apply_confidence_gating(
    results: List[Dict[str, Any]],
    threshold: float = CONFIDENCE_THRESHOLD,
) -> tuple[List[Dict[str, Any]], int]:
    """
    Filter results by confidence threshold.

    Returns:
        (filtered_results, count_of_filtered_out)
    """
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
    require_policy_ack: bool = False,
    policy_acknowledged: bool = False,
) -> IntelligenceResponse:
    """
    Enforce the full intelligence contract on a set of results.

    1. Validates schema for each result
    2. Applies confidence gating
    3. Checks policy acknowledgement if required
    4. Returns standardized response envelope

    Raises:
        HTTPException: If policy acknowledgement required but not provided
    """
    # Policy acknowledgement check
    if require_policy_ack and not policy_acknowledged:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "POLICY_ACK_REQUIRED",
                "message": "Policy acknowledgement required to view intelligence results",
            }
        )

    # Validate all results against schema
    valid_results = []
    for result in results:
        is_valid, error = validate_intelligence_result(result)
        if is_valid:
            valid_results.append(result)
        # Invalid results are silently dropped (downgraded)

    # Apply confidence gating
    gated_results, filtered_count = apply_confidence_gating(valid_results, threshold)

    return {
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
    """
    Wrap raw intelligence results in the standard contract envelope.

    This is a convenience function for routes that want full control
    but still want the standard envelope structure.
    """
    enforced = enforce_contract(results)

    response = {
        "ok": enforced["ok"],
        "mode": enforced["mode"],
        "writes_allowed": enforced["writes_allowed"],
        result_key: enforced["results"],
        "filtered_count": enforced["filtered_count"],
        "guardrails": enforced["guardrails"],
    }

    # Add any extra fields
    response.update(extra_fields)

    return response

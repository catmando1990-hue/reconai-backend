# app/guardrails/intelligence_contract.py
"""
Intelligence Contract Enforcement (STEP 3)

Enforces Canonical AI Laws:
1. Advisory-only (read-only, no writes, no auto-exec)
2. Manual-run only (no background or implicit calls)
3. Confidence gating: surface results ONLY if confidence >= 0.85
4. Mandatory response schema: {confidence, explanation, evidence}
5. Block or downgrade responses that fail schema or confidence

CONTRACT VERSION: 1
- intelligence_version: ALWAYS present in response (integer)
- lifecycle: ALWAYS present in response (status + reason_code)
- evidence: ALWAYS present in response (metadata for auditability)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Literal, Optional, TypedDict
from fastapi import HTTPException


# =============================================================================
# CONTRACT VERSION (Strict versioning, no silent changes)
# =============================================================================

# Contract version - increment on breaking changes to Intelligence API
INTELLIGENCE_CONTRACT_VERSION = 1

# Contract constants
CONFIDENCE_THRESHOLD = 0.85
MODE = "advisory"
WRITES_ALLOWED = False


# =============================================================================
# LIFECYCLE MODEL (PART 1)
# =============================================================================

# Valid lifecycle statuses - fail-closed validation
IntelligenceLifecycleStatus = Literal["success", "partial", "failed", "no_data"]
VALID_LIFECYCLE_STATUSES: FrozenSet[str] = frozenset(["success", "partial", "failed", "no_data"])


class IntelligenceLifecycle(TypedDict):
    """
    Lifecycle state for Intelligence responses.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise
    """
    status: IntelligenceLifecycleStatus
    reason_code: Optional[str]


def create_intelligence_lifecycle(
    status: str,
    reason_code: Optional[str] = None,
) -> IntelligenceLifecycle:
    """
    Factory for creating validated IntelligenceLifecycle.
    Fail-closed: rejects invalid status values.

    Args:
        status: Must be one of: success, partial, failed, no_data
        reason_code: Required when status != "success"

    Raises:
        ValueError: If status is invalid or reason_code missing when required
    """
    if status not in VALID_LIFECYCLE_STATUSES:
        raise ValueError(
            f"Invalid lifecycle status: {status}. "
            f"Must be one of: {sorted(VALID_LIFECYCLE_STATUSES)}"
        )

    # Enforce reason_code requirement
    if status != "success" and not reason_code:
        raise ValueError(
            f"reason_code is required when status is '{status}'"
        )

    # Clear reason_code for success status
    if status == "success":
        reason_code = None

    return {
        "status": status,  # type: ignore
        "reason_code": reason_code,
    }


# =============================================================================
# EVIDENCE METADATA (PART 2)
# =============================================================================

class IntelligenceEvidenceMetadata(TypedDict):
    """
    Evidence metadata for auditability of Intelligence insights.

    CONTRACT:
    - sources: ALWAYS present (list of data sources used)
    - coverage_window: ALWAYS present (time range of data analyzed)
    - evaluated_at: ALWAYS present (ISO timestamp of evaluation)
    - confidence_score: ALWAYS present (overall confidence 0.0-1.0)
    """
    sources: List[str]
    coverage_window: Dict[str, Optional[str]]  # {"start": ISO, "end": ISO}
    evaluated_at: str  # ISO timestamp
    confidence_score: float  # 0.0 to 1.0


def create_evidence_metadata(
    sources: List[str],
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    evaluated_at: Optional[str] = None,
    confidence_score: float = 0.0,
) -> IntelligenceEvidenceMetadata:
    """
    Factory for creating validated IntelligenceEvidenceMetadata.

    Args:
        sources: List of data sources (e.g., ["transactions", "classifications"])
        coverage_start: ISO timestamp for start of data window
        coverage_end: ISO timestamp for end of data window
        evaluated_at: ISO timestamp of evaluation (defaults to now)
        confidence_score: Overall confidence (0.0-1.0)

    Raises:
        ValueError: If confidence_score is out of range
    """
    if not (0.0 <= confidence_score <= 1.0):
        raise ValueError(
            f"confidence_score must be between 0.0 and 1.0, got: {confidence_score}"
        )

    return {
        "sources": sources or [],
        "coverage_window": {
            "start": coverage_start,
            "end": coverage_end,
        },
        "evaluated_at": evaluated_at or datetime.utcnow().isoformat(),
        "confidence_score": confidence_score,
    }


class IntelligenceResult(TypedDict, total=False):
    """Required schema for all intelligence results."""
    confidence: float
    explanation: str
    evidence: List[Any]


class IntelligenceResponse(TypedDict):
    """
    Standard intelligence response envelope.

    CONTRACT VERSION: 1
    - intelligence_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """
    intelligence_version: int  # ALWAYS present - contract version
    lifecycle: IntelligenceLifecycle  # ALWAYS present
    evidence: IntelligenceEvidenceMetadata  # ALWAYS present
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
    sources: Optional[List[str]] = None,
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
) -> IntelligenceResponse:
    """
    Enforce the full intelligence contract on a set of results.

    1. Validates schema for each result
    2. Applies confidence gating
    3. Checks policy acknowledgement if required
    4. Computes lifecycle and evidence metadata
    5. Returns standardized response envelope

    Raises:
        HTTPException: If policy acknowledgement required but not provided
    """
    now = datetime.utcnow().isoformat()

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
    invalid_count = 0
    for result in results:
        is_valid, error = validate_intelligence_result(result)
        if is_valid:
            valid_results.append(result)
        else:
            invalid_count += 1
        # Invalid results are silently dropped (downgraded)

    # Apply confidence gating
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

    # Compute average confidence for evidence metadata
    avg_confidence = 0.0
    if gated_results:
        avg_confidence = sum(r.get("confidence", 0.0) for r in gated_results) / len(gated_results)

    # Build evidence metadata
    evidence_meta = create_evidence_metadata(
        sources=sources or ["intelligence_contract"],
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        evaluated_at=now,
        confidence_score=avg_confidence,
    )

    return {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
        "lifecycle": lifecycle,  # ALWAYS present
        "evidence": evidence_meta,  # ALWAYS present
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
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    **extra_fields,
) -> Dict[str, Any]:
    """
    Wrap raw intelligence results in the standard contract envelope.

    This is a convenience function for routes that want full control
    but still want the standard envelope structure.

    CONTRACT VERSION: 1
    - intelligence_version: ALWAYS present in response
    - lifecycle: ALWAYS present in response
    - evidence: ALWAYS present in response
    """
    enforced = enforce_contract(
        results,
        sources=sources,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )

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

    # Add any extra fields
    response.update(extra_fields)

    return response

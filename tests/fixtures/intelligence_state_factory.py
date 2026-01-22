"""
CANONICAL INTELLIGENCE STATE FACTORY

Single source of truth for Intelligence response mock data in tests.
EVERY Intelligence test MUST use this factory - no inline mocks allowed.

CONTRACT VERSION: 1
Schema mirrors: app/intelligence/models.py, app/guardrails/intelligence_contract.py

CANONICAL LAWS:
- intelligence_version is ALWAYS present (integer, currently 1)
- lifecycle is ALWAYS present with status + reason_code
- evidence is ALWAYS present (auditability requirement)
- reason_code is REQUIRED when lifecycle.status != "success"
- confidence must be 0.0-1.0 for all confidence scores

RULES:
- Factory produces valid Intelligence responses by default
- Use builder methods for test-specific variations
- Schema changes MUST update this file FIRST
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.guardrails.intelligence_contract import (
    INTELLIGENCE_CONTRACT_VERSION,
    VALID_LIFECYCLE_STATUSES,
)


# =============================================================================
# SCHEMA ASSERTION HELPER
# =============================================================================


class IntelligenceSchemaValidationError(Exception):
    """Raised when an Intelligence response object violates the canonical schema."""

    def __init__(self, message: str, field: str = "", value: Any = None):
        super().__init__(message)
        self.field = field
        self.value = value


def assert_valid_intelligence_state(state: Dict[str, Any], context: str = "") -> None:
    """
    Assert an Intelligence response dict matches the canonical schema.
    FAIL-CLOSED: Raises immediately on any violation.

    This validates common fields present in all Intelligence responses:
    - ClassifyResponse
    - TransactionOverlayResponse

    Args:
        state: The state dict to validate
        context: Optional context for error messages

    Raises:
        IntelligenceSchemaValidationError: If schema is violated
    """
    prefix = f"[{context}] " if context else ""

    if not isinstance(state, dict):
        raise IntelligenceSchemaValidationError(
            f"{prefix}Intelligence state must be a dict, got {type(state).__name__}",
            "root",
            state,
        )

    # =========================================================================
    # PART 1: intelligence_version - REQUIRED, must be int
    # =========================================================================

    if "intelligence_version" not in state:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Missing required field: intelligence_version",
            "intelligence_version",
            None,
        )

    if not isinstance(state["intelligence_version"], int):
        raise IntelligenceSchemaValidationError(
            f"{prefix}intelligence_version must be int, got {type(state['intelligence_version']).__name__}",
            "intelligence_version",
            state["intelligence_version"],
        )

    if state["intelligence_version"] != INTELLIGENCE_CONTRACT_VERSION:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Unsupported intelligence_version: {state['intelligence_version']}. "
            f"Expected: {INTELLIGENCE_CONTRACT_VERSION}",
            "intelligence_version",
            state["intelligence_version"],
        )

    # =========================================================================
    # PART 2: lifecycle - REQUIRED, must have status and reason_code
    # =========================================================================

    if "lifecycle" not in state:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Missing required field: lifecycle",
            "lifecycle",
            None,
        )

    _assert_valid_lifecycle(state["lifecycle"], f"{prefix}lifecycle")

    # =========================================================================
    # PART 3: evidence - REQUIRED for auditability
    # =========================================================================

    if "evidence" not in state:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Missing required field: evidence",
            "evidence",
            None,
        )

    _assert_valid_evidence(state["evidence"], f"{prefix}evidence")

    # =========================================================================
    # PART 4: Common fields - ok, request_id
    # =========================================================================

    if "ok" not in state:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Missing required field: ok",
            "ok",
            None,
        )

    if not isinstance(state["ok"], bool):
        raise IntelligenceSchemaValidationError(
            f"{prefix}ok must be bool, got {type(state['ok']).__name__}",
            "ok",
            state["ok"],
        )

    if "request_id" not in state:
        raise IntelligenceSchemaValidationError(
            f"{prefix}Missing required field: request_id",
            "request_id",
            None,
        )

    if not isinstance(state["request_id"], str):
        raise IntelligenceSchemaValidationError(
            f"{prefix}request_id must be str, got {type(state['request_id']).__name__}",
            "request_id",
            state["request_id"],
        )


def _assert_valid_lifecycle(lifecycle: Any, context: str) -> None:
    """Validate lifecycle object."""
    if not isinstance(lifecycle, dict):
        raise IntelligenceSchemaValidationError(
            f"{context} must be dict, got {type(lifecycle).__name__}",
            context,
            lifecycle,
        )

    required_fields = {"status", "reason_code"}

    for field_name in required_fields:
        if field_name not in lifecycle:
            raise IntelligenceSchemaValidationError(
                f"{context}: Missing required field: {field_name}",
                f"{context}.{field_name}",
                None,
            )

    # Validate status enum
    if not isinstance(lifecycle["status"], str):
        raise IntelligenceSchemaValidationError(
            f"{context}.status must be str, got {type(lifecycle['status']).__name__}",
            f"{context}.status",
            lifecycle["status"],
        )

    if lifecycle["status"] not in VALID_LIFECYCLE_STATUSES:
        raise IntelligenceSchemaValidationError(
            f"{context}.status must be one of {sorted(VALID_LIFECYCLE_STATUSES)}, "
            f"got '{lifecycle['status']}'",
            f"{context}.status",
            lifecycle["status"],
        )

    # reason_code is REQUIRED when status != "success"
    if lifecycle["status"] != "success":
        if lifecycle["reason_code"] is None:
            raise IntelligenceSchemaValidationError(
                f"{context}.reason_code is required when status is '{lifecycle['status']}'",
                f"{context}.reason_code",
                lifecycle["reason_code"],
            )

        if not isinstance(lifecycle["reason_code"], str):
            raise IntelligenceSchemaValidationError(
                f"{context}.reason_code must be str, got {type(lifecycle['reason_code']).__name__}",
                f"{context}.reason_code",
                lifecycle["reason_code"],
            )


def _assert_valid_evidence(evidence: Any, context: str) -> None:
    """Validate evidence metadata object."""
    if not isinstance(evidence, dict):
        raise IntelligenceSchemaValidationError(
            f"{context} must be dict, got {type(evidence).__name__}",
            context,
            evidence,
        )

    required_fields = {"sources", "coverage_window", "evaluated_at", "confidence_score"}

    for field_name in required_fields:
        if field_name not in evidence:
            raise IntelligenceSchemaValidationError(
                f"{context}: Missing required field: {field_name}",
                f"{context}.{field_name}",
                None,
            )

    # sources must be a list
    if not isinstance(evidence["sources"], list):
        raise IntelligenceSchemaValidationError(
            f"{context}.sources must be list, got {type(evidence['sources']).__name__}",
            f"{context}.sources",
            evidence["sources"],
        )

    # coverage_window must be a dict with start and end
    if not isinstance(evidence["coverage_window"], dict):
        raise IntelligenceSchemaValidationError(
            f"{context}.coverage_window must be dict, got {type(evidence['coverage_window']).__name__}",
            f"{context}.coverage_window",
            evidence["coverage_window"],
        )

    if "start" not in evidence["coverage_window"] or "end" not in evidence["coverage_window"]:
        raise IntelligenceSchemaValidationError(
            f"{context}.coverage_window must have 'start' and 'end' keys",
            f"{context}.coverage_window",
            evidence["coverage_window"],
        )

    # evaluated_at must be string
    if not isinstance(evidence["evaluated_at"], str):
        raise IntelligenceSchemaValidationError(
            f"{context}.evaluated_at must be str, got {type(evidence['evaluated_at']).__name__}",
            f"{context}.evaluated_at",
            evidence["evaluated_at"],
        )

    # confidence_score must be float 0.0-1.0
    if not isinstance(evidence["confidence_score"], (int, float)):
        raise IntelligenceSchemaValidationError(
            f"{context}.confidence_score must be number, got {type(evidence['confidence_score']).__name__}",
            f"{context}.confidence_score",
            evidence["confidence_score"],
        )

    if not (0.0 <= evidence["confidence_score"] <= 1.0):
        raise IntelligenceSchemaValidationError(
            f"{context}.confidence_score must be between 0.0 and 1.0, got {evidence['confidence_score']}",
            f"{context}.confidence_score",
            evidence["confidence_score"],
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _generate_request_id() -> str:
    """Generate a test request ID."""
    return f"intel_test_{uuid4().hex[:16]}"


def _iso_now() -> str:
    """Generate current ISO timestamp."""
    return datetime.utcnow().isoformat()


# =============================================================================
# EVIDENCE BUILDER
# =============================================================================


def evidence_factory(
    *,
    sources: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    confidence_score: float = 0.85,
) -> Dict[str, Any]:
    """
    Create a valid EvidenceMetadata dict.

    Args:
        sources: Data sources used
        start_date: Coverage window start (ISO8601)
        end_date: Coverage window end (ISO8601)
        confidence_score: Overall confidence (0.0-1.0)

    Returns:
        Valid EvidenceMetadata as a dict
    """
    return {
        "sources": sources or ["mvp_transactions", "transaction_classifications"],
        "coverage_window": {"start": start_date, "end": end_date},
        "evaluated_at": _iso_now(),
        "confidence_score": confidence_score,
    }


def empty_evidence(reason: str = "No data available") -> Dict[str, Any]:
    """Create empty evidence for no-data scenarios."""
    return {
        "sources": [],
        "coverage_window": {"start": None, "end": None},
        "evaluated_at": _iso_now(),
        "confidence_score": 0.0,
    }


# =============================================================================
# LIFECYCLE BUILDER
# =============================================================================


def lifecycle_factory(
    status: str = "success",
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a valid lifecycle dict.

    Enforces canonical law: reason_code required when status != "success"

    Args:
        status: Lifecycle status (success, partial, failed, no_data)
        reason_code: Reason code (required for non-success)

    Returns:
        Valid lifecycle as a dict
    """
    if status != "success" and reason_code is None:
        reason_code = "unknown"

    return {
        "status": status,
        "reason_code": reason_code if status != "success" else None,
    }


# =============================================================================
# CLASSIFICATION RESULT BUILDER
# =============================================================================


def classification_result_factory(
    *,
    transaction_id: Optional[str] = None,
    category: str = "business_expense",
    confidence: float = 0.90,
    explanation: str = "Classified based on merchant pattern",
    requires_review: bool = False,
) -> Dict[str, Any]:
    """
    Create a valid ClassificationResult dict.

    Args:
        transaction_id: Transaction ID (auto-generated if not provided)
        category: Classification category
        confidence: Confidence score (0.0-1.0)
        explanation: Classification explanation
        requires_review: Whether manual review is required

    Returns:
        Valid ClassificationResult as a dict
    """
    return {
        "transaction_id": transaction_id or f"tx_{uuid4().hex[:12]}",
        "category": category,
        "confidence": confidence,
        "explanation": explanation,
        "evidence": [
            {
                "evidence_type": "merchant_pattern",
                "value": "Office Depot",
                "weight": 0.8,
                "description": "Merchant name matches business supply pattern",
            }
        ],
        "requires_review": requires_review or confidence < 0.85,
        "matched_rules": ["business_supplies_rule"],
        "classified_at": _iso_now(),
    }


# =============================================================================
# INTELLIGENCE CLASSIFY RESPONSE FACTORY
# =============================================================================


def intelligence_classify_factory(
    *,
    lifecycle_status: str = "success",
    reason_code: Optional[str] = None,
    request_id: Optional[str] = None,
    classifications: Optional[List[Dict[str, Any]]] = None,
    duplicates: Optional[List[Dict[str, Any]]] = None,
    confidence_score: float = 0.90,
) -> Dict[str, Any]:
    """
    Create a valid ClassifyResponse dict.

    Args:
        lifecycle_status: Lifecycle status
        reason_code: Reason code for non-success states
        request_id: Request ID (auto-generated if not provided)
        classifications: List of classification results
        duplicates: List of duplicate groups
        confidence_score: Overall confidence score

    Returns:
        Valid ClassifyResponse as a dict
    """
    cls_list = classifications or [classification_result_factory()]
    dup_list = duplicates or []

    flagged_count = sum(1 for c in cls_list if c.get("requires_review", False))

    result = {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,
        "lifecycle": lifecycle_factory(lifecycle_status, reason_code),
        "evidence": evidence_factory(
            sources=["mvp_transactions", "transaction_classifications"],
            start_date="2024-01-01T00:00:00",
            end_date=_iso_now(),
            confidence_score=confidence_score,
        ),
        "ok": lifecycle_status == "success",
        "request_id": request_id or _generate_request_id(),
        "classified_at": _iso_now(),
        "classifications": cls_list,
        "duplicates": dup_list,
        "total_processed": len(cls_list),
        "flagged_for_review": flagged_count,
        "audit_event_id": f"audit_{uuid4().hex[:12]}",
        "guardrails": {
            "confidence_threshold": 0.85,
            "writes_to_transactions": False,
            "advisory_only": False,
            "manual_run_only": True,
        },
    }

    # Validate the result
    assert_valid_intelligence_state(result, "intelligence_classify_factory")

    return result


# =============================================================================
# INTELLIGENCE OVERLAY RESPONSE FACTORY
# =============================================================================


def intelligence_overlay_factory(
    *,
    lifecycle_status: str = "success",
    reason_code: Optional[str] = None,
    request_id: Optional[str] = None,
    transactions: Optional[List[Dict[str, Any]]] = None,
    confidence_score: float = 0.85,
) -> Dict[str, Any]:
    """
    Create a valid TransactionOverlayResponse dict.

    Args:
        lifecycle_status: Lifecycle status
        reason_code: Reason code for non-success states
        request_id: Request ID (auto-generated if not provided)
        transactions: List of transactions with overlays
        confidence_score: Overall confidence score

    Returns:
        Valid TransactionOverlayResponse as a dict
    """
    tx_list = transactions or [
        {
            "transaction_id": f"tx_{uuid4().hex[:12]}",
            "tx_date": "2024-01-15",
            "amount": -150.00,
            "description": "Office supplies",
            "merchant": "Office Depot",
            "original_category": "Shopping",
            "classification": classification_result_factory(),
            "duplicate_group": None,
            "has_classification": True,
            "last_classified_at": _iso_now(),
        }
    ]

    classified_count = sum(1 for t in tx_list if t.get("has_classification", False))
    flagged_count = sum(
        1 for t in tx_list
        if t.get("classification", {}).get("requires_review", False)
    )

    result = {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,
        "lifecycle": lifecycle_factory(lifecycle_status, reason_code),
        "evidence": evidence_factory(
            sources=["mvp_transactions", "transaction_classifications"],
            start_date="2024-01-01T00:00:00",
            end_date=_iso_now(),
            confidence_score=confidence_score,
        ),
        "ok": lifecycle_status == "success",
        "request_id": request_id or _generate_request_id(),
        "generated_at": _iso_now(),
        "transactions": tx_list,
        "total_count": len(tx_list),
        "classified_count": classified_count,
        "unclassified_count": len(tx_list) - classified_count,
        "flagged_count": flagged_count,
        "guardrails": {
            "read_only": True,
            "source_table": "mvp_transactions",
            "overlay_tables": ["transaction_classifications", "transaction_evidence"],
        },
    }

    # Validate the result
    assert_valid_intelligence_state(result, "intelligence_overlay_factory")

    return result


# =============================================================================
# PRESET FACTORIES - Common test scenarios
# =============================================================================


def success_intelligence_classify() -> Dict[str, Any]:
    """
    Success state - Valid classification results ready for display.
    Use for testing normal classification display.
    """
    return intelligence_classify_factory(
        lifecycle_status="success",
        classifications=[
            classification_result_factory(confidence=0.95),
            classification_result_factory(confidence=0.88),
            classification_result_factory(confidence=0.92),
        ],
        confidence_score=0.92,
    )


def partial_intelligence_classify(reason_code: str = "low_confidence") -> Dict[str, Any]:
    """
    Partial state - Some classifications available but with issues.
    Use for testing partial data display.
    """
    return intelligence_classify_factory(
        lifecycle_status="partial",
        reason_code=reason_code,
        classifications=[
            classification_result_factory(confidence=0.70, requires_review=True),
        ],
        confidence_score=0.70,
    )


def failed_intelligence_classify(reason_code: str = "computation_error") -> Dict[str, Any]:
    """
    Failed state - Classification failed.
    Use for testing error states.
    """
    return intelligence_classify_factory(
        lifecycle_status="failed",
        reason_code=reason_code,
        classifications=[],
        confidence_score=0.0,
    )


def no_data_intelligence_classify(reason_code: str = "insufficient_data") -> Dict[str, Any]:
    """
    No data state - Not enough data for classification.
    Use for testing empty states.
    """
    return intelligence_classify_factory(
        lifecycle_status="no_data",
        reason_code=reason_code,
        classifications=[],
        confidence_score=0.0,
    )


def success_intelligence_overlay() -> Dict[str, Any]:
    """
    Success state - Valid overlay data ready for display.
    Use for testing transaction overlay display.
    """
    return intelligence_overlay_factory(
        lifecycle_status="success",
        confidence_score=0.90,
    )


def low_confidence_intelligence_classify() -> Dict[str, Any]:
    """
    Success state but low confidence - all below threshold.
    Use for testing confidence thresholds.
    """
    return intelligence_classify_factory(
        lifecycle_status="success",
        classifications=[
            classification_result_factory(confidence=0.60, requires_review=True),
            classification_result_factory(confidence=0.55, requires_review=True),
        ],
        confidence_score=0.58,
    )

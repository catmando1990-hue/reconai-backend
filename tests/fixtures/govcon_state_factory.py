# tests/fixtures/govcon_state_factory.py
"""
GovCon / DCAA Compliance State Factory (Test Infrastructure)

Canonical test data factory for all GovCon/DCAA tests.
FAIL-CLOSED: rejects invalid state instead of inferring.

CONTRACT VERSION: 1
- govcon_version: ALWAYS present, integer (value = 1)
- lifecycle: ALWAYS present (status + reason_code)
- evidence: ALWAYS present (metadata for auditability)

All tests MUST use these factories - no inline mocks allowed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, FrozenSet

from app.govcon.contract import (
    GOVCON_CONTRACT_VERSION,
    VALID_GOVCON_LIFECYCLE_STATUSES,
)


# =============================================================================
# SCHEMA VALIDATION (FAIL-CLOSED)
# =============================================================================


class GovConSchemaValidationError(Exception):
    """
    Raised when GovCon state fails schema validation.

    FAIL-CLOSED: Invalid state is rejected, not inferred or auto-corrected.
    """
    pass


# Valid lifecycle statuses for factory
GovConLifecycleStatus = Literal["success", "partial", "failed", "no_data"]


def assert_valid_govcon_state(state: Dict[str, Any]) -> None:
    """
    Assert that a GovCon state dict matches the contract schema.
    FAIL-CLOSED: Throws on any violation.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer (value = GOVCON_CONTRACT_VERSION)
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (documents, sources, coverage_window, last_verified_at, dcaa_compliant)

    Args:
        state: GovCon state dict to validate

    Raises:
        GovConSchemaValidationError: If state violates contract
    """
    errors: List[str] = []

    # ==========================================================================
    # GOVCON_VERSION (CONTRACT REQUIRED)
    # ==========================================================================
    if "govcon_version" not in state:
        errors.append("MISSING: govcon_version (CONTRACT REQUIRED)")
    elif not isinstance(state["govcon_version"], int):
        errors.append(f"INVALID: govcon_version must be int, got {type(state['govcon_version']).__name__}")
    elif state["govcon_version"] != GOVCON_CONTRACT_VERSION:
        errors.append(f"INVALID: govcon_version must be {GOVCON_CONTRACT_VERSION}, got {state['govcon_version']}")

    # ==========================================================================
    # LIFECYCLE (CONTRACT REQUIRED)
    # ==========================================================================
    if "lifecycle" not in state:
        errors.append("MISSING: lifecycle (CONTRACT REQUIRED)")
    else:
        lifecycle = state["lifecycle"]
        if not isinstance(lifecycle, dict):
            errors.append(f"INVALID: lifecycle must be dict, got {type(lifecycle).__name__}")
        else:
            # Validate status
            if "status" not in lifecycle:
                errors.append("MISSING: lifecycle.status (CONTRACT REQUIRED)")
            elif lifecycle["status"] not in VALID_GOVCON_LIFECYCLE_STATUSES:
                errors.append(
                    f"INVALID: lifecycle.status must be one of {sorted(VALID_GOVCON_LIFECYCLE_STATUSES)}, "
                    f"got '{lifecycle['status']}'"
                )
            else:
                # Validate reason_code requirement
                status = lifecycle["status"]
                reason_code = lifecycle.get("reason_code")

                if status != "success" and not reason_code:
                    errors.append(
                        f"MISSING: lifecycle.reason_code (REQUIRED when status='{status}')"
                    )
                if status == "success" and reason_code is not None:
                    errors.append(
                        f"INVALID: lifecycle.reason_code must be None when status='success', "
                        f"got '{reason_code}'"
                    )

    # ==========================================================================
    # EVIDENCE (CONTRACT REQUIRED)
    # ==========================================================================
    if "evidence" not in state:
        errors.append("MISSING: evidence (CONTRACT REQUIRED)")
    else:
        evidence = state["evidence"]
        if not isinstance(evidence, dict):
            errors.append(f"INVALID: evidence must be dict, got {type(evidence).__name__}")
        else:
            # Required evidence fields
            required_evidence_fields = [
                "documents",
                "sources",
                "coverage_window",
                "last_verified_at",
                "dcaa_compliant",
            ]
            for field in required_evidence_fields:
                if field not in evidence:
                    errors.append(f"MISSING: evidence.{field} (CONTRACT REQUIRED)")

            # Type validation for evidence fields
            if "documents" in evidence and not isinstance(evidence["documents"], list):
                errors.append(f"INVALID: evidence.documents must be list, got {type(evidence['documents']).__name__}")

            if "sources" in evidence and not isinstance(evidence["sources"], list):
                errors.append(f"INVALID: evidence.sources must be list, got {type(evidence['sources']).__name__}")

            if "coverage_window" in evidence:
                cw = evidence["coverage_window"]
                if not isinstance(cw, dict):
                    errors.append(f"INVALID: evidence.coverage_window must be dict, got {type(cw).__name__}")
                elif "start" not in cw or "end" not in cw:
                    errors.append("INVALID: evidence.coverage_window must have 'start' and 'end' keys")

            if "last_verified_at" in evidence and not isinstance(evidence["last_verified_at"], str):
                errors.append(f"INVALID: evidence.last_verified_at must be str, got {type(evidence['last_verified_at']).__name__}")

            if "dcaa_compliant" in evidence and not isinstance(evidence["dcaa_compliant"], bool):
                errors.append(f"INVALID: evidence.dcaa_compliant must be bool, got {type(evidence['dcaa_compliant']).__name__}")

    # ==========================================================================
    # FAIL IF ANY ERRORS
    # ==========================================================================
    if errors:
        error_list = "\n  - ".join(errors)
        raise GovConSchemaValidationError(
            f"GovCon state validation failed ({len(errors)} errors):\n  - {error_list}"
        )


# =============================================================================
# LIFECYCLE FACTORY
# =============================================================================


def govcon_lifecycle_factory(
    status: GovConLifecycleStatus = "success",
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a valid GovCon lifecycle dict.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise

    Args:
        status: Lifecycle status
        reason_code: Reason code (required for non-success)

    Returns:
        Valid lifecycle dict

    Raises:
        ValueError: If reason_code missing for non-success status
    """
    if status not in VALID_GOVCON_LIFECYCLE_STATUSES:
        raise ValueError(
            f"Invalid status: {status}. Must be one of: {sorted(VALID_GOVCON_LIFECYCLE_STATUSES)}"
        )

    if status != "success" and not reason_code:
        raise ValueError(f"reason_code is required when status is '{status}'")

    # Clear reason_code for success
    if status == "success":
        reason_code = None

    return {
        "status": status,
        "reason_code": reason_code,
    }


# =============================================================================
# EVIDENCE FACTORY
# =============================================================================


def govcon_evidence_factory(
    documents: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    last_verified_at: Optional[str] = None,
    dcaa_compliant: bool = True,
) -> Dict[str, Any]:
    """
    Create a valid GovCon evidence metadata dict.

    CONTRACT:
    - documents: ALWAYS present (list of supporting document references)
    - sources: ALWAYS present (list of data sources used)
    - coverage_window: ALWAYS present (time range of data analyzed)
    - last_verified_at: ALWAYS present (ISO timestamp of last verification)
    - dcaa_compliant: ALWAYS present (boolean indicating DCAA compliance)

    Args:
        documents: Supporting document references (e.g., FAR citations)
        sources: Data sources used
        coverage_start: ISO timestamp for start of data window
        coverage_end: ISO timestamp for end of data window
        last_verified_at: ISO timestamp of last verification
        dcaa_compliant: Whether the data is DCAA compliant

    Returns:
        Valid evidence metadata dict
    """
    now = datetime.utcnow().isoformat()

    return {
        "documents": documents or [],
        "sources": sources or ["govcon_state_factory"],
        "coverage_window": {
            "start": coverage_start,
            "end": coverage_end,
        },
        "last_verified_at": last_verified_at or now,
        "dcaa_compliant": dcaa_compliant,
    }


def govcon_empty_evidence() -> Dict[str, Any]:
    """Create empty evidence metadata for testing failure cases."""
    return govcon_evidence_factory(
        documents=[],
        sources=[],
        dcaa_compliant=False,
    )


# =============================================================================
# CLASSIFICATION FACTORIES
# =============================================================================


def govcon_classification_factory(
    transaction_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    allowability: str = "allowable",
    cost_pool: str = "direct_labor",
    far_citation: Optional[str] = "FAR_31_201_2",
    requires_review: bool = False,
    evidence_chain: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Create a valid GovCon classification dict.

    Args:
        transaction_id: Transaction ID
        organization_id: Organization ID
        allowability: Allowability status
        cost_pool: Cost pool type
        far_citation: FAR citation
        requires_review: Whether requires review
        evidence_chain: Evidence chain items

    Returns:
        Valid classification dict
    """
    now = datetime.utcnow().isoformat()

    return {
        "id": str(uuid.uuid4()),
        "organization_id": organization_id or f"org_{uuid.uuid4().hex[:8]}",
        "transaction_id": transaction_id or f"txn_{uuid.uuid4().hex[:8]}",
        "allowability": allowability,
        "far_citation": far_citation,
        "allowability_notes": None,
        "cost_pool": cost_pool,
        "cost_pool_notes": None,
        "intelligence_classification_id": None,
        "requires_review": requires_review,
        "reviewed_by": None if requires_review else "system",
        "reviewed_at": None if requires_review else now,
        "evidence_chain": evidence_chain or [],
        "classified_by": "govcon_state_factory",
        "classified_at": now,
    }


def govcon_transaction_overlay_factory(
    transaction_id: Optional[str] = None,
    amount: float = 1000.0,
    description: str = "Test transaction",
    has_govcon_classification: bool = True,
    dcaa_compliant: bool = True,
    requires_review: bool = False,
    evidence_complete: bool = True,
) -> Dict[str, Any]:
    """
    Create a valid GovCon transaction overlay dict.

    Args:
        transaction_id: Transaction ID
        amount: Transaction amount
        description: Transaction description
        has_govcon_classification: Whether has GovCon classification
        dcaa_compliant: Whether DCAA compliant
        requires_review: Whether requires review
        evidence_complete: Whether evidence is complete

    Returns:
        Valid transaction overlay dict
    """
    txn_id = transaction_id or f"txn_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    return {
        "transaction_id": txn_id,
        "tx_date": now[:10],  # YYYY-MM-DD
        "amount": amount,
        "description": description,
        "merchant": "Test Vendor",
        "original_category": "Other",
        "intelligence_category": "professional_services" if has_govcon_classification else None,
        "intelligence_confidence": 0.95 if has_govcon_classification else None,
        "govcon_classification": govcon_classification_factory(
            transaction_id=txn_id,
            requires_review=requires_review,
        ) if has_govcon_classification else None,
        "has_govcon_classification": has_govcon_classification,
        "dcaa_compliant": dcaa_compliant,
        "requires_review": requires_review,
        "evidence_complete": evidence_complete,
    }


# =============================================================================
# TRANSACTIONS RESPONSE FACTORY
# =============================================================================


def govcon_transactions_factory(
    lifecycle_status: GovConLifecycleStatus = "success",
    lifecycle_reason: Optional[str] = None,
    transactions: Optional[List[Dict[str, Any]]] = None,
    total_count: Optional[int] = None,
    classified_count: Optional[int] = None,
    allowable_count: Optional[int] = None,
    unallowable_count: Optional[int] = None,
    pending_review_count: Optional[int] = None,
    dcaa_compliant: bool = True,
) -> Dict[str, Any]:
    """
    Create a valid GovConTransactionsResponse dict.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)

    Args:
        lifecycle_status: Lifecycle status
        lifecycle_reason: Reason code (required for non-success)
        transactions: List of transaction overlays
        total_count: Total transaction count
        classified_count: Classified transaction count
        allowable_count: Allowable transaction count
        unallowable_count: Unallowable transaction count
        pending_review_count: Pending review count
        dcaa_compliant: Whether DCAA compliant

    Returns:
        Valid GovConTransactionsResponse dict
    """
    now = datetime.utcnow().isoformat()

    # Default transactions
    if transactions is None:
        if lifecycle_status == "success":
            transactions = [
                govcon_transaction_overlay_factory(),
                govcon_transaction_overlay_factory(amount=2000.0, description="Second transaction"),
            ]
        else:
            transactions = []

    # Calculate counts from transactions if not provided
    if total_count is None:
        total_count = len(transactions)
    if classified_count is None:
        classified_count = sum(1 for t in transactions if t.get("has_govcon_classification"))
    if allowable_count is None:
        allowable_count = sum(
            1 for t in transactions
            if (t.get("govcon_classification") or {}).get("allowability") == "allowable"
        )
    if unallowable_count is None:
        unallowable_count = sum(
            1 for t in transactions
            if (t.get("govcon_classification") or {}).get("allowability") == "unallowable"
        )
    if pending_review_count is None:
        pending_review_count = sum(1 for t in transactions if t.get("requires_review"))

    return {
        # CONTRACT REQUIRED FIELDS
        "govcon_version": GOVCON_CONTRACT_VERSION,
        "lifecycle": govcon_lifecycle_factory(lifecycle_status, lifecycle_reason),
        "evidence": govcon_evidence_factory(
            sources=["govcon_classifications", "evidence_chain"],
            dcaa_compliant=dcaa_compliant,
        ),
        # Response fields
        "ok": lifecycle_status == "success",
        "request_id": f"req_{uuid.uuid4().hex[:12]}",
        "generated_at": now,
        "transactions": transactions,
        "total_count": total_count,
        "classified_count": classified_count,
        "allowable_count": allowable_count,
        "unallowable_count": unallowable_count,
        "pending_review_count": pending_review_count,
        "guardrails": {
            "read_only": True,
            "source_table": "mvp_transactions",
            "overlay_tables": ["govcon_classifications", "govcon_evidence_chain"],
            "dcaa_compliant": dcaa_compliant,
        },
    }


# =============================================================================
# PRESET FACTORIES - TRANSACTIONS
# =============================================================================


def success_govcon_transactions() -> Dict[str, Any]:
    """Create successful GovCon transactions response."""
    return govcon_transactions_factory(
        lifecycle_status="success",
        dcaa_compliant=True,
    )


def partial_govcon_transactions() -> Dict[str, Any]:
    """Create partial GovCon transactions response (some unclassified)."""
    return govcon_transactions_factory(
        lifecycle_status="partial",
        lifecycle_reason="INCOMPLETE_CLASSIFICATION",
        transactions=[
            govcon_transaction_overlay_factory(has_govcon_classification=True),
            govcon_transaction_overlay_factory(has_govcon_classification=False),
        ],
        dcaa_compliant=False,
    )


def failed_govcon_transactions() -> Dict[str, Any]:
    """Create failed GovCon transactions response."""
    return govcon_transactions_factory(
        lifecycle_status="failed",
        lifecycle_reason="CLASSIFICATION_ERROR",
        transactions=[],
        dcaa_compliant=False,
    )


def no_data_govcon_transactions() -> Dict[str, Any]:
    """Create no-data GovCon transactions response."""
    return govcon_transactions_factory(
        lifecycle_status="no_data",
        lifecycle_reason="NO_TRANSACTIONS",
        transactions=[],
        dcaa_compliant=False,
    )


def pending_review_govcon_transactions() -> Dict[str, Any]:
    """Create GovCon transactions response with pending reviews."""
    return govcon_transactions_factory(
        lifecycle_status="partial",
        lifecycle_reason="PENDING_REVIEW",
        transactions=[
            govcon_transaction_overlay_factory(requires_review=True, dcaa_compliant=False),
            govcon_transaction_overlay_factory(requires_review=True, dcaa_compliant=False),
        ],
        dcaa_compliant=False,
    )


# =============================================================================
# EXPORT PREVIEW FACTORY
# =============================================================================


def export_preview_item_factory(
    transaction_id: Optional[str] = None,
    amount: float = 1000.0,
    cost_pool: str = "direct_labor",
    allowability: str = "allowable",
    far_citation: Optional[str] = "FAR_31_201_2",
    evidence_count: int = 3,
    dcaa_compliant: bool = True,
) -> Dict[str, Any]:
    """
    Create a valid export preview item dict.

    Args:
        transaction_id: Transaction ID
        amount: Transaction amount
        cost_pool: Cost pool type
        allowability: Allowability status
        far_citation: FAR citation
        evidence_count: Number of evidence items
        dcaa_compliant: Whether DCAA compliant

    Returns:
        Valid export preview item dict
    """
    now = datetime.utcnow().isoformat()

    return {
        "transaction_id": transaction_id or f"txn_{uuid.uuid4().hex[:8]}",
        "tx_date": now[:10],
        "amount": amount,
        "description": "Test transaction for export",
        "cost_pool": cost_pool,
        "allowability": allowability,
        "far_citation": far_citation,
        "evidence_count": evidence_count,
        "dcaa_compliant": dcaa_compliant,
    }


def govcon_export_preview_factory(
    lifecycle_status: GovConLifecycleStatus = "success",
    lifecycle_reason: Optional[str] = None,
    preview: Optional[List[Dict[str, Any]]] = None,
    export_ready: bool = True,
    blocking_issues: Optional[List[str]] = None,
    dcaa_compliant: bool = True,
) -> Dict[str, Any]:
    """
    Create a valid ExportPreviewResponse dict.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)

    Args:
        lifecycle_status: Lifecycle status
        lifecycle_reason: Reason code (required for non-success)
        preview: List of export preview items
        export_ready: Whether export is ready
        blocking_issues: List of blocking issues
        dcaa_compliant: Whether DCAA compliant

    Returns:
        Valid ExportPreviewResponse dict
    """
    now = datetime.utcnow().isoformat()

    # Default preview items
    if preview is None:
        if lifecycle_status == "success":
            preview = [
                export_preview_item_factory(),
                export_preview_item_factory(amount=2000.0, cost_pool="direct_material"),
            ]
        else:
            preview = []

    return {
        # CONTRACT REQUIRED FIELDS
        "govcon_version": GOVCON_CONTRACT_VERSION,
        "lifecycle": govcon_lifecycle_factory(lifecycle_status, lifecycle_reason),
        "evidence": govcon_evidence_factory(
            sources=["govcon_export"],
            documents=["FAR_31_201", "CAS_418"],
            dcaa_compliant=dcaa_compliant,
        ),
        # Response fields
        "ok": lifecycle_status == "success",
        "request_id": f"req_{uuid.uuid4().hex[:12]}",
        "generated_at": now,
        "preview": preview,
        "summary": {
            "total_items": len(preview),
            "total_amount": sum(item.get("amount", 0) for item in preview),
            "allowable_amount": sum(
                item.get("amount", 0) for item in preview
                if item.get("allowability") == "allowable"
            ),
        },
        "export_ready": export_ready,
        "blocking_issues": blocking_issues or [],
        "audit_event_id": f"audit_{uuid.uuid4().hex[:8]}",
        "guardrails": {
            "auto_export": False,
            "manual_trigger_required": True,
            "dcaa_compliant": dcaa_compliant,
            "immutable_audit": True,
        },
    }


# =============================================================================
# PRESET FACTORIES - EXPORT PREVIEW
# =============================================================================


def success_export_preview() -> Dict[str, Any]:
    """Create successful export preview response."""
    return govcon_export_preview_factory(
        lifecycle_status="success",
        export_ready=True,
        dcaa_compliant=True,
    )


def blocked_export_preview() -> Dict[str, Any]:
    """Create blocked export preview response."""
    return govcon_export_preview_factory(
        lifecycle_status="partial",
        lifecycle_reason="BLOCKING_ISSUES",
        export_ready=False,
        blocking_issues=[
            "2 transactions require review",
            "Missing FAR citation for 1 transaction",
        ],
        dcaa_compliant=False,
    )


def failed_export_preview() -> Dict[str, Any]:
    """Create failed export preview response."""
    return govcon_export_preview_factory(
        lifecycle_status="failed",
        lifecycle_reason="EXPORT_ERROR",
        preview=[],
        export_ready=False,
        dcaa_compliant=False,
    )


# =============================================================================
# SELF-TEST (Run with: python -m tests.fixtures.govcon_state_factory)
# =============================================================================


def _run_self_tests() -> None:
    """Run self-tests to verify factory produces valid state."""
    print("Running GovCon state factory self-tests...")

    test_cases = [
        ("success_govcon_transactions", success_govcon_transactions),
        ("partial_govcon_transactions", partial_govcon_transactions),
        ("failed_govcon_transactions", failed_govcon_transactions),
        ("no_data_govcon_transactions", no_data_govcon_transactions),
        ("pending_review_govcon_transactions", pending_review_govcon_transactions),
        ("success_export_preview", success_export_preview),
        ("blocked_export_preview", blocked_export_preview),
        ("failed_export_preview", failed_export_preview),
    ]

    passed = 0
    failed = 0

    for name, factory in test_cases:
        try:
            state = factory()
            assert_valid_govcon_state(state)
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")

    if failed > 0:
        raise SystemExit(1)

    print("\n✓ All GovCon state factory tests passed!")


if __name__ == "__main__":
    _run_self_tests()

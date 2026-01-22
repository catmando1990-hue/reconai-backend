"""
CANONICAL CFO STATE FACTORY

Single source of truth for CFO response mock data in tests.
EVERY CFO test MUST use this factory - no inline mocks allowed.

CONTRACT VERSION: 1
Schema mirrors: app/cfo/models.py

CANONICAL LAWS:
- cfo_version is ALWAYS present (integer, currently 1)
- lifecycle is ALWAYS present with status + reason_code
- evidence is ALWAYS present (auditability requirement)
- reason_code is REQUIRED when lifecycle.status != "success"

RULES:
- Factory produces valid CFO responses by default
- Use builder methods for test-specific variations
- Schema changes MUST update this file FIRST
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.cfo.models import (
    CFO_CONTRACT_VERSION,
    VALID_CFO_LIFECYCLE_STATUSES,
    CFOLifecycleStatus,
    CFOLifecycle,
    EvidenceMetadata,
    CashFlowRollup,
    BurnRateMetrics,
    ForecastProjection,
    ForecastSeries,
    FinancialException,
    CFOOverviewResponse,
    ForecastResponse,
    ExceptionsResponse,
)


# =============================================================================
# SCHEMA ASSERTION HELPER
# =============================================================================


class CfoSchemaValidationError(Exception):
    """Raised when a CFO response object violates the canonical schema."""

    def __init__(self, message: str, field: str = "", value: Any = None):
        super().__init__(message)
        self.field = field
        self.value = value


def assert_valid_cfo_state(state: Dict[str, Any], context: str = "") -> None:
    """
    Assert a CFO response dict matches the canonical schema.
    FAIL-CLOSED: Raises immediately on any violation.

    This validates common fields present in all CFO responses:
    - CFOOverviewResponse
    - ForecastResponse
    - ExceptionsResponse

    Args:
        state: The state dict to validate
        context: Optional context for error messages

    Raises:
        CfoSchemaValidationError: If schema is violated
    """
    prefix = f"[{context}] " if context else ""

    if not isinstance(state, dict):
        raise CfoSchemaValidationError(
            f"{prefix}CFO state must be a dict, got {type(state).__name__}",
            "root",
            state,
        )

    # =========================================================================
    # PART 1: cfo_version - REQUIRED, must be int
    # =========================================================================

    if "cfo_version" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: cfo_version",
            "cfo_version",
            None,
        )

    if not isinstance(state["cfo_version"], int):
        raise CfoSchemaValidationError(
            f"{prefix}cfo_version must be int, got {type(state['cfo_version']).__name__}",
            "cfo_version",
            state["cfo_version"],
        )

    if state["cfo_version"] != CFO_CONTRACT_VERSION:
        raise CfoSchemaValidationError(
            f"{prefix}Unsupported cfo_version: {state['cfo_version']}. Expected: {CFO_CONTRACT_VERSION}",
            "cfo_version",
            state["cfo_version"],
        )

    # =========================================================================
    # PART 2: lifecycle - REQUIRED, must have status and reason_code
    # =========================================================================

    if "lifecycle" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: lifecycle",
            "lifecycle",
            None,
        )

    _assert_valid_lifecycle(state["lifecycle"], f"{prefix}lifecycle")

    # =========================================================================
    # PART 3: evidence - REQUIRED for auditability
    # =========================================================================

    if "evidence" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: evidence",
            "evidence",
            None,
        )

    _assert_valid_evidence(state["evidence"], f"{prefix}evidence")

    # =========================================================================
    # PART 4: Common fields - ok, request_id, org_id, generated_at
    # =========================================================================

    if "ok" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: ok",
            "ok",
            None,
        )

    if not isinstance(state["ok"], bool):
        raise CfoSchemaValidationError(
            f"{prefix}ok must be bool, got {type(state['ok']).__name__}",
            "ok",
            state["ok"],
        )

    if "request_id" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: request_id",
            "request_id",
            None,
        )

    if not isinstance(state["request_id"], str):
        raise CfoSchemaValidationError(
            f"{prefix}request_id must be str, got {type(state['request_id']).__name__}",
            "request_id",
            state["request_id"],
        )

    if "org_id" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: org_id",
            "org_id",
            None,
        )

    if not isinstance(state["org_id"], str):
        raise CfoSchemaValidationError(
            f"{prefix}org_id must be str, got {type(state['org_id']).__name__}",
            "org_id",
            state["org_id"],
        )

    if "generated_at" not in state:
        raise CfoSchemaValidationError(
            f"{prefix}Missing required field: generated_at",
            "generated_at",
            None,
        )

    if not isinstance(state["generated_at"], str):
        raise CfoSchemaValidationError(
            f"{prefix}generated_at must be str, got {type(state['generated_at']).__name__}",
            "generated_at",
            state["generated_at"],
        )


def _assert_valid_lifecycle(lifecycle: Any, context: str) -> None:
    """Validate lifecycle object."""
    if not isinstance(lifecycle, dict):
        raise CfoSchemaValidationError(
            f"{context} must be dict, got {type(lifecycle).__name__}",
            context,
            lifecycle,
        )

    required_fields = {"status", "reason_code"}

    for field_name in required_fields:
        if field_name not in lifecycle:
            raise CfoSchemaValidationError(
                f"{context}: Missing required field: {field_name}",
                f"{context}.{field_name}",
                None,
            )

    # Validate status enum
    if not isinstance(lifecycle["status"], str):
        raise CfoSchemaValidationError(
            f"{context}.status must be str, got {type(lifecycle['status']).__name__}",
            f"{context}.status",
            lifecycle["status"],
        )

    if lifecycle["status"] not in VALID_CFO_LIFECYCLE_STATUSES:
        raise CfoSchemaValidationError(
            f"{context}.status must be one of {sorted(VALID_CFO_LIFECYCLE_STATUSES)}, "
            f"got '{lifecycle['status']}'",
            f"{context}.status",
            lifecycle["status"],
        )

    # reason_code is REQUIRED when status != "success"
    if lifecycle["status"] != "success":
        if lifecycle["reason_code"] is None:
            raise CfoSchemaValidationError(
                f"{context}.reason_code is required when status is '{lifecycle['status']}'",
                f"{context}.reason_code",
                lifecycle["reason_code"],
            )

        if not isinstance(lifecycle["reason_code"], str):
            raise CfoSchemaValidationError(
                f"{context}.reason_code must be str, got {type(lifecycle['reason_code']).__name__}",
                f"{context}.reason_code",
                lifecycle["reason_code"],
            )


def _assert_valid_evidence(evidence: Any, context: str) -> None:
    """Validate evidence metadata object."""
    if not isinstance(evidence, dict):
        raise CfoSchemaValidationError(
            f"{context} must be dict, got {type(evidence).__name__}",
            context,
            evidence,
        )

    required_fields = {"sources", "coverage_window", "last_updated_at"}

    for field_name in required_fields:
        if field_name not in evidence:
            raise CfoSchemaValidationError(
                f"{context}: Missing required field: {field_name}",
                f"{context}.{field_name}",
                None,
            )

    # sources must be a list
    if not isinstance(evidence["sources"], list):
        raise CfoSchemaValidationError(
            f"{context}.sources must be list, got {type(evidence['sources']).__name__}",
            f"{context}.sources",
            evidence["sources"],
        )

    # coverage_window must be a dict with start and end
    if not isinstance(evidence["coverage_window"], dict):
        raise CfoSchemaValidationError(
            f"{context}.coverage_window must be dict, got {type(evidence['coverage_window']).__name__}",
            f"{context}.coverage_window",
            evidence["coverage_window"],
        )

    if "start" not in evidence["coverage_window"] or "end" not in evidence["coverage_window"]:
        raise CfoSchemaValidationError(
            f"{context}.coverage_window must have 'start' and 'end' keys",
            f"{context}.coverage_window",
            evidence["coverage_window"],
        )

    # last_updated_at must be string
    if not isinstance(evidence["last_updated_at"], str):
        raise CfoSchemaValidationError(
            f"{context}.last_updated_at must be str, got {type(evidence['last_updated_at']).__name__}",
            f"{context}.last_updated_at",
            evidence["last_updated_at"],
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _generate_request_id() -> str:
    """Generate a test request ID."""
    return f"cfo_test_{uuid4().hex[:16]}"


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
    record_count: int = 0,
    confidence_note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a valid EvidenceMetadata dict.

    Args:
        sources: Data sources used
        start_date: Coverage window start (ISO8601)
        end_date: Coverage window end (ISO8601)
        record_count: Number of records used
        confidence_note: Optional confidence note

    Returns:
        Valid EvidenceMetadata as a dict
    """
    return {
        "sources": sources or ["mvp_transactions"],
        "coverage_window": {"start": start_date, "end": end_date},
        "last_updated_at": _iso_now(),
        "record_count": record_count,
        "confidence_note": confidence_note,
    }


def empty_evidence(reason: str = "No data available") -> Dict[str, Any]:
    """Create empty evidence for no-data scenarios."""
    return {
        "sources": [],
        "coverage_window": {"start": None, "end": None},
        "last_updated_at": _iso_now(),
        "record_count": 0,
        "confidence_note": reason,
    }


# =============================================================================
# LIFECYCLE BUILDER
# =============================================================================

# Default reason codes per non-success status (fail-closed: no silent defaults)
_DEFAULT_REASON_CODES: Dict[str, str] = {
    "partial": "PARTIAL_DATA",
    "failed": "COMPUTATION_ERROR",
    "no_data": "INSUFFICIENT_DATA",
}


def lifecycle_factory(
    status: CFOLifecycleStatus = "success",
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a valid lifecycle dict.

    Enforces canonical law: reason_code required when status != "success"

    Args:
        status: Lifecycle status
        reason_code: Reason code (required for non-success, uses explicit default if omitted)

    Returns:
        Valid lifecycle as a dict

    Raises:
        ValueError: If status is invalid or reason_code missing for non-success with no default
    """
    if status != "success" and reason_code is None:
        # Use explicit default reason_code per status (fail-closed)
        reason_code = _DEFAULT_REASON_CODES.get(status)
        if reason_code is None:
            raise ValueError(
                f"reason_code is required for lifecycle status '{status}' "
                f"and no default is defined"
            )

    return {
        "status": status,
        "reason_code": reason_code,
    }


def lifecycle_success() -> Dict[str, Any]:
    """Factory for success lifecycle (reason_code=None)."""
    return {"status": "success", "reason_code": None}


def lifecycle_partial(reason_code: str = "PARTIAL_DATA") -> Dict[str, Any]:
    """
    Factory for partial lifecycle.

    Args:
        reason_code: Required reason code (default: PARTIAL_DATA)

    Returns:
        Valid lifecycle dict with status="partial"
    """
    return {"status": "partial", "reason_code": reason_code}


def lifecycle_failed(reason_code: str = "COMPUTATION_ERROR") -> Dict[str, Any]:
    """
    Factory for failed lifecycle.

    Args:
        reason_code: Required reason code (default: COMPUTATION_ERROR)

    Returns:
        Valid lifecycle dict with status="failed"
    """
    return {"status": "failed", "reason_code": reason_code}


def lifecycle_no_data(reason_code: str = "INSUFFICIENT_DATA") -> Dict[str, Any]:
    """
    Factory for no_data lifecycle.

    Args:
        reason_code: Required reason code (default: INSUFFICIENT_DATA)

    Returns:
        Valid lifecycle dict with status="no_data"
    """
    return {"status": "no_data", "reason_code": reason_code}


# =============================================================================
# CFO OVERVIEW FACTORY
# =============================================================================


def cfo_overview_factory(
    *,
    lifecycle_status: CFOLifecycleStatus = "success",
    reason_code: Optional[str] = None,
    org_id: str = "org_test123",
    request_id: Optional[str] = None,
    kpis: Optional[Dict[str, Any]] = None,
    monthly_rollups: Optional[List[Dict[str, Any]]] = None,
    quarterly_rollups: Optional[List[Dict[str, Any]]] = None,
    burn_rate: Optional[Dict[str, Any]] = None,
    evidence_sources: Optional[List[str]] = None,
    record_count: int = 100,
) -> Dict[str, Any]:
    """
    Create a valid CFOOverviewResponse dict.

    Args:
        lifecycle_status: Lifecycle status
        reason_code: Reason code for non-success states
        org_id: Organization ID
        request_id: Request ID (auto-generated if not provided)
        kpis: Key performance indicators
        monthly_rollups: Monthly cash flow rollups
        quarterly_rollups: Quarterly cash flow rollups
        burn_rate: Burn rate metrics
        evidence_sources: Data sources for evidence
        record_count: Number of records used

    Returns:
        Valid CFOOverviewResponse as a dict
    """
    result = {
        "cfo_version": CFO_CONTRACT_VERSION,
        "lifecycle": lifecycle_factory(lifecycle_status, reason_code),
        "evidence": evidence_factory(
            sources=evidence_sources or ["mvp_transactions", "plaid_accounts"],
            start_date="2024-01-01T00:00:00",
            end_date=_iso_now(),
            record_count=record_count,
        ),
        "ok": lifecycle_status == "success",
        "request_id": request_id or _generate_request_id(),
        "org_id": org_id,
        "generated_at": _iso_now(),
        "kpis": kpis or {
            "cash_balance": 50000.0,
            "burn_rate": 10000.0,
            "runway_months": 5.0,
        },
        "monthly_rollups": monthly_rollups or [],
        "quarterly_rollups": quarterly_rollups or [],
        "burn_rate": burn_rate,
        "guardrails": {
            "read_only": True,
            "auto_refresh": False,
            "manual_trigger_required": True,
        },
        "advisory": {
            "mode": "computed",
            "disclaimer": "Financial data is for informational purposes only.",
        },
    }

    # Validate the result
    assert_valid_cfo_state(result, "cfo_overview_factory")

    return result


# =============================================================================
# CFO FORECAST FACTORY
# =============================================================================


def cfo_forecast_factory(
    *,
    lifecycle_status: CFOLifecycleStatus = "success",
    reason_code: Optional[str] = None,
    org_id: str = "org_test123",
    request_id: Optional[str] = None,
    forecasts: Optional[List[Dict[str, Any]]] = None,
    overall_confidence: float = 0.75,
    evidence_sources: Optional[List[str]] = None,
    record_count: int = 90,
) -> Dict[str, Any]:
    """
    Create a valid ForecastResponse dict.

    Args:
        lifecycle_status: Lifecycle status
        reason_code: Reason code for non-success states
        org_id: Organization ID
        request_id: Request ID (auto-generated if not provided)
        forecasts: List of forecast projections
        overall_confidence: Overall confidence score (0-1)
        evidence_sources: Data sources for evidence
        record_count: Number of records used

    Returns:
        Valid ForecastResponse as a dict
    """
    result = {
        "cfo_version": CFO_CONTRACT_VERSION,
        "lifecycle": lifecycle_factory(lifecycle_status, reason_code),
        "evidence": evidence_factory(
            sources=evidence_sources or ["mvp_transactions"],
            start_date="2024-01-01T00:00:00",
            end_date=_iso_now(),
            record_count=record_count,
        ),
        "ok": lifecycle_status == "success",
        "request_id": request_id or _generate_request_id(),
        "org_id": org_id,
        "generated_at": _iso_now(),
        "forecasts": {
            "forecasts": forecasts or [],
            "overall_confidence": overall_confidence,
            "min_confidence": overall_confidence * 0.8,
            "max_confidence": min(overall_confidence * 1.2, 1.0),
            "historical_data_points": record_count,
            "historical_period_days": 90,
            "all_values_are_projections": True,
        },
        "audit_event_id": f"audit_{uuid4().hex[:12]}",
        "guardrails": {
            "read_only": True,
            "auto_refresh": False,
            "projections_not_facts": True,
            "confidence_threshold": 0.85,
        },
        "disclaimer": (
            "ALL VALUES ARE PROJECTIONS. These forecasts are based on historical data "
            "and assumptions. Actual results may differ materially. Do not use as sole "
            "basis for financial decisions."
        ),
    }

    # Validate the result
    assert_valid_cfo_state(result, "cfo_forecast_factory")

    return result


# =============================================================================
# CFO EXCEPTIONS FACTORY
# =============================================================================


def cfo_exceptions_factory(
    *,
    lifecycle_status: CFOLifecycleStatus = "success",
    reason_code: Optional[str] = None,
    org_id: str = "org_test123",
    request_id: Optional[str] = None,
    exceptions: Optional[List[Dict[str, Any]]] = None,
    evidence_sources: Optional[List[str]] = None,
    record_count: int = 50,
) -> Dict[str, Any]:
    """
    Create a valid ExceptionsResponse dict.

    Args:
        lifecycle_status: Lifecycle status
        reason_code: Reason code for non-success states
        org_id: Organization ID
        request_id: Request ID (auto-generated if not provided)
        exceptions: List of financial exceptions
        evidence_sources: Data sources for evidence
        record_count: Number of records used

    Returns:
        Valid ExceptionsResponse as a dict
    """
    exc_list = exceptions or []
    critical_count = sum(1 for e in exc_list if e.get("severity") == "critical")
    high_count = sum(1 for e in exc_list if e.get("severity") == "high")

    result = {
        "cfo_version": CFO_CONTRACT_VERSION,
        "lifecycle": lifecycle_factory(lifecycle_status, reason_code),
        "evidence": evidence_factory(
            sources=evidence_sources or ["mvp_transactions"],
            start_date="2024-01-01T00:00:00",
            end_date=_iso_now(),
            record_count=record_count,
        ),
        "ok": lifecycle_status == "success",
        "request_id": request_id or _generate_request_id(),
        "org_id": org_id,
        "generated_at": _iso_now(),
        "exceptions": exc_list,
        "total_count": len(exc_list),
        "critical_count": critical_count,
        "high_count": high_count,
        "limit": 50,
        "offset": 0,
        "guardrails": {
            "read_only": True,
            "detection_only": True,
            "no_auto_remediation": True,
        },
    }

    # Validate the result
    assert_valid_cfo_state(result, "cfo_exceptions_factory")

    return result


# =============================================================================
# PRESET FACTORIES - Common test scenarios
# =============================================================================


def success_cfo_overview() -> Dict[str, Any]:
    """
    Success state - Valid CFO overview data ready for display.
    Use for testing normal CFO display.
    """
    return cfo_overview_factory(
        lifecycle_status="success",
        kpis={
            "cash_balance": 150000.0,
            "burn_rate": 25000.0,
            "runway_months": 6.0,
        },
        record_count=500,
    )


def partial_cfo_overview(reason_code: str = "PARTIAL_DATA") -> Dict[str, Any]:
    """
    Partial state - Some CFO data available but incomplete.
    Use for testing partial data display.

    Args:
        reason_code: Required reason code (default: PARTIAL_DATA)
    """
    return cfo_overview_factory(
        lifecycle_status="partial",
        reason_code=reason_code,
        kpis={
            "cash_balance": 50000.0,
            "burn_rate": None,
            "runway_months": None,
        },
        record_count=50,
    )


def failed_cfo_overview(reason_code: str = "COMPUTATION_ERROR") -> Dict[str, Any]:
    """
    Failed state - CFO computation failed.
    Use for testing error states.

    Args:
        reason_code: Required reason code (default: COMPUTATION_ERROR)
    """
    return cfo_overview_factory(
        lifecycle_status="failed",
        reason_code=reason_code,
        kpis={},
        record_count=0,
    )


def no_data_cfo_overview(reason_code: str = "INSUFFICIENT_DATA") -> Dict[str, Any]:
    """
    No data state - Not enough data for CFO analysis.
    Use for testing empty states.

    Args:
        reason_code: Required reason code (default: INSUFFICIENT_DATA)
    """
    return cfo_overview_factory(
        lifecycle_status="no_data",
        reason_code=reason_code,
        kpis={},
        evidence_sources=[],
        record_count=0,
    )


def success_cfo_forecast() -> Dict[str, Any]:
    """
    Success state - Valid forecast data.
    Use for testing forecast display.
    """
    return cfo_forecast_factory(
        lifecycle_status="success",
        overall_confidence=0.78,
        record_count=90,
    )


def low_confidence_cfo_forecast() -> Dict[str, Any]:
    """
    Success state but low confidence - requires review flag.
    Use for testing confidence thresholds.
    """
    return cfo_forecast_factory(
        lifecycle_status="success",
        overall_confidence=0.45,
        record_count=30,
    )


def success_cfo_exceptions() -> Dict[str, Any]:
    """
    Success state - Exceptions detected and ready for review.
    Use for testing exception display.
    """
    return cfo_exceptions_factory(
        lifecycle_status="success",
        exceptions=[
            {
                "exception_id": f"exc_{uuid4().hex[:8]}",
                "exception_type": "unusual_expense",
                "severity": "high",
                "transaction_id": "tx_123",
                "description": "Unusually large expense",
                "explanation": "This expense is 3x the typical amount",
                "expected_value": "1000.00",
                "actual_value": "3500.00",
                "deviation_pct": "250.00",
                "z_score": 3.2,
                "threshold_used": 2.0,
                "requires_review": True,
                "review_priority": 2,
                "detected_at": _iso_now(),
            },
        ],
        record_count=100,
    )


# =============================================================================
# EXCEPTION BUILDERS
# =============================================================================


def financial_exception_factory(
    *,
    exception_type: str = "unusual_expense",
    severity: str = "medium",
    description: str = "Detected financial anomaly",
    explanation: str = "This transaction deviates from expected patterns",
) -> Dict[str, Any]:
    """
    Create a valid FinancialException dict.

    Args:
        exception_type: Type of exception
        severity: Severity level (low, medium, high, critical)
        description: Short description
        explanation: Detailed explanation

    Returns:
        Valid FinancialException as a dict
    """
    return {
        "exception_id": f"exc_{uuid4().hex[:8]}",
        "exception_type": exception_type,
        "severity": severity,
        "transaction_id": f"tx_{uuid4().hex[:8]}",
        "description": description,
        "explanation": explanation,
        "expected_value": None,
        "actual_value": None,
        "deviation_pct": None,
        "z_score": None,
        "threshold_used": None,
        "requires_review": True,
        "review_priority": 3,
        "detected_at": _iso_now(),
    }

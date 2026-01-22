# app/cfo/models.py
"""
CFO / Financial Controls Models (Phase 3)

Pydantic models for cash flow rollups, burn rate, forecasts, and exceptions.
All projections explicitly labeled as non-factual.

CANONICAL LAWS:
- Projections ≠ facts
- Confidence < 0.85 must be flagged
- Decimal precision for financial data
- All responses include cfo_version for contract tracking

CONTRACT VERSION: 1
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional, Dict, Any

from pydantic import BaseModel, Field


# =============================================================================
# CFO CONTRACT VERSION (Strict versioning, no silent changes)
# =============================================================================

# Contract version - increment on breaking changes to CFO API
CFO_CONTRACT_VERSION = 1


# =============================================================================
# CFO LIFECYCLE MODEL (Explicit state, no inference)
# =============================================================================

# Valid lifecycle statuses - fail-closed validation
CFOLifecycleStatus = Literal["success", "partial", "failed", "no_data"]
VALID_CFO_LIFECYCLE_STATUSES = frozenset({"success", "partial", "failed", "no_data"})


class CFOLifecycleValidationError(ValueError):
    """Raised when lifecycle status is invalid. Fail-closed design."""
    pass


def validate_cfo_lifecycle_status(status: str) -> CFOLifecycleStatus:
    """
    Validate CFO lifecycle status. Fail-closed: reject invalid values.

    Args:
        status: The lifecycle status to validate

    Returns:
        The validated status (unchanged if valid)

    Raises:
        CFOLifecycleValidationError: If status is not in VALID_CFO_LIFECYCLE_STATUSES
    """
    if status not in VALID_CFO_LIFECYCLE_STATUSES:
        raise CFOLifecycleValidationError(
            f"Invalid CFO lifecycle status: '{status}'. "
            f"Valid values: {sorted(VALID_CFO_LIFECYCLE_STATUSES)}"
        )
    return status  # type: ignore


class CFOLifecycle(BaseModel):
    """
    Explicit lifecycle state for CFO responses.

    CANONICAL LAW: lifecycle MUST always be present.
    CANONICAL LAW: reason_code MUST be present when status != 'success'.

    Domain guard enforced via __init__, not Pydantic validators.
    Raises CFOLifecycleValidationError (not generic ValidationError).
    """

    status: CFOLifecycleStatus = Field(
        description="Lifecycle status: success | partial | failed | no_data"
    )
    reason_code: Optional[str] = Field(
        default=None,
        description="Required when status != 'success'. Explains why not fully successful."
    )

    def __init__(self, **data):
        """
        Construct CFOLifecycle with explicit domain guard.

        Raises:
            CFOLifecycleValidationError: If lifecycle invariants are violated.
                - Invalid status value
                - Missing reason_code when status != 'success'
        """
        super().__init__(**data)
        # Fail-closed status validation
        validate_cfo_lifecycle_status(self.status)
        # Domain invariant: reason_code required for non-success
        if self.status != "success" and not self.reason_code:
            raise CFOLifecycleValidationError(
                f"reason_code is required when lifecycle status is '{self.status}'"
            )

    @classmethod
    def success(cls) -> "CFOLifecycle":
        """Factory for success lifecycle."""
        return cls(status="success", reason_code=None)

    @classmethod
    def partial(cls, reason_code: str) -> "CFOLifecycle":
        """Factory for partial lifecycle (some data available)."""
        return cls(status="partial", reason_code=reason_code)

    @classmethod
    def failed(cls, reason_code: str) -> "CFOLifecycle":
        """Factory for failed lifecycle."""
        return cls(status="failed", reason_code=reason_code)

    @classmethod
    def no_data(cls, reason_code: str) -> "CFOLifecycle":
        """Factory for no_data lifecycle."""
        return cls(status="no_data", reason_code=reason_code)


# =============================================================================
# EVIDENCE METADATA MODEL (Auditability)
# =============================================================================


class EvidenceMetadata(BaseModel):
    """
    Evidence metadata for CFO metrics.

    CANONICAL LAW: Every metric MUST have evidence metadata.
    CANONICAL LAW: sources, coverage_window, and last_updated_at MUST be present.
    """

    sources: List[str] = Field(
        description="Data sources used (e.g., ['mvp_transactions', 'plaid_accounts'])"
    )
    coverage_window: Dict[str, Optional[str]] = Field(
        description="Time window covered: {start: ISO8601, end: ISO8601}"
    )
    last_updated_at: str = Field(
        description="When evidence was last refreshed (ISO8601)"
    )
    record_count: int = Field(
        default=0,
        description="Number of records used to compute metrics"
    )
    confidence_note: Optional[str] = Field(
        default=None,
        description="Optional note about data quality or confidence"
    )

    @classmethod
    def create(
        cls,
        sources: List[str],
        start_date: Optional[str],
        end_date: Optional[str],
        record_count: int = 0,
        confidence_note: Optional[str] = None,
    ) -> "EvidenceMetadata":
        """Factory method for creating evidence metadata."""
        return cls(
            sources=sources,
            coverage_window={"start": start_date, "end": end_date},
            last_updated_at=datetime.utcnow().isoformat(),
            record_count=record_count,
            confidence_note=confidence_note,
        )

    @classmethod
    def empty(cls, reason: str) -> "EvidenceMetadata":
        """Factory for empty evidence (no data available)."""
        return cls(
            sources=[],
            coverage_window={"start": None, "end": None},
            last_updated_at=datetime.utcnow().isoformat(),
            record_count=0,
            confidence_note=reason,
        )


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

PeriodType = Literal["monthly", "quarterly", "yearly"]
TrendDirection = Literal["accelerating", "stable", "improving", "unknown"]
ExceptionSeverity = Literal["low", "medium", "high", "critical"]
ExceptionType = Literal[
    "unusual_expense",
    "duplicate_suspected",
    "amount_outlier",
    "frequency_anomaly",
    "category_mismatch",
    "missing_data",
]


# ============================================================================
# CASH FLOW ROLLUP MODELS
# ============================================================================


class CashFlowRollup(BaseModel):
    """Cash flow aggregation for a specific period."""

    period_type: PeriodType
    period_label: str = Field(description="Human-readable period label (e.g., '2024-01', 'Q1 2024')")
    period_start: date
    period_end: date

    # Inflows
    total_inflows: Decimal = Decimal("0.00")
    revenue_inflows: Decimal = Decimal("0.00")
    other_inflows: Decimal = Decimal("0.00")

    # Outflows
    total_outflows: Decimal = Decimal("0.00")
    operating_expenses: Decimal = Decimal("0.00")
    payroll_expenses: Decimal = Decimal("0.00")
    other_outflows: Decimal = Decimal("0.00")

    # Net
    net_cash_flow: Decimal = Decimal("0.00")

    # Metadata
    transaction_count: int = 0
    computed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class BurnRateMetrics(BaseModel):
    """Burn rate calculation based on historical data."""

    # Current state
    current_cash_balance: Decimal = Decimal("0.00")

    # Burn rate calculations
    monthly_burn_rate: Decimal = Decimal("0.00")
    weekly_burn_rate: Decimal = Decimal("0.00")
    daily_burn_rate: Decimal = Decimal("0.00")

    # Trend analysis
    burn_trend: TrendDirection = "unknown"
    burn_trend_pct_change: Decimal = Decimal("0.00")

    # Runway calculation
    runway_months: Optional[Decimal] = None
    runway_weeks: Optional[Decimal] = None

    # Data basis
    calculation_period_days: int = 90
    data_points_used: int = 0

    # Confidence
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    requires_review: bool = True

    # Metadata
    computed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================================
# FORECAST MODELS
# ============================================================================


class ForecastProjection(BaseModel):
    """
    Projected financial state at a future point.

    IMPORTANT: This is a PROJECTION, not a fact.
    All projections are advisory only and subject to uncertainty.
    """

    # Projection identification
    forecast_id: str
    projection_date: date = Field(description="The date this projection is for")
    horizon_days: int = Field(description="Days from today")

    # Projected values
    projected_cash_balance: Decimal = Decimal("0.00")
    projected_monthly_burn: Decimal = Decimal("0.00")
    projected_runway_months: Optional[Decimal] = None

    # Assumptions used
    growth_assumption: str = Field(default="linear", description="Model assumption (linear, conservative, optimistic)")
    assumptions_detail: Dict[str, Any] = Field(default_factory=dict)

    # Confidence scoring
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    confidence_factors: List[str] = Field(default_factory=list, description="Factors affecting confidence")
    requires_review: bool = True

    # Explicit projection disclaimer
    is_projection: bool = Field(default=True, description="ALWAYS True - this is NOT a fact")
    projection_disclaimer: str = Field(
        default="This is a PROJECTION based on historical data. Actual results may vary significantly.",
        description="Legal disclaimer for projection"
    )

    # Metadata
    computed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ForecastSeries(BaseModel):
    """Time series of forecast projections."""

    forecasts: List[ForecastProjection] = Field(default_factory=list)

    # Overall confidence
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    min_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    max_confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    # Data basis
    historical_data_points: int = 0
    historical_period_days: int = 0

    # Explicit labeling
    all_values_are_projections: bool = Field(
        default=True,
        description="ALWAYS True - all forecast values are projections, not facts"
    )


# ============================================================================
# EXCEPTION MODELS
# ============================================================================


class FinancialException(BaseModel):
    """Detected financial anomaly or exception."""

    exception_id: str
    exception_type: ExceptionType
    severity: ExceptionSeverity

    # Context
    transaction_id: Optional[str] = None
    description: str
    explanation: str

    # Detection metrics
    expected_value: Optional[Decimal] = None
    actual_value: Optional[Decimal] = None
    deviation_pct: Optional[Decimal] = None

    # Statistical basis
    z_score: Optional[float] = None
    threshold_used: Optional[float] = None

    # Review status
    requires_review: bool = True
    review_priority: int = Field(ge=1, le=5, default=3, description="1=highest priority")

    # Metadata
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================================
# API RESPONSE MODELS
# ============================================================================


class CFOOverviewResponse(BaseModel):
    """
    Response for GET /api/cfo/overview.

    CONTRACT VERSION: 1
    - cfo_version: ALWAYS present, integer
    - lifecycle: ALWAYS present, explicit state
    - evidence: ALWAYS present, auditability metadata
    """

    # Contract version - ALWAYS present
    cfo_version: int = CFO_CONTRACT_VERSION

    # Lifecycle - ALWAYS present (no inference)
    lifecycle: CFOLifecycle = Field(
        description="Explicit lifecycle state. reason_code required when status != 'success'"
    )

    # Evidence metadata - ALWAYS present (auditability)
    evidence: EvidenceMetadata = Field(
        description="Data sources, coverage window, and freshness"
    )

    ok: bool = True
    request_id: str

    # Organization context
    org_id: str
    generated_at: str

    # KPIs
    kpis: Dict[str, Any] = Field(
        default_factory=dict,
        description="Key performance indicators (cash_balance, burn_rate, runway)"
    )

    # Rollups
    monthly_rollups: List[CashFlowRollup] = Field(default_factory=list)
    quarterly_rollups: List[CashFlowRollup] = Field(default_factory=list)

    # Burn rate
    burn_rate: Optional[BurnRateMetrics] = None

    # Guardrails
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "read_only": True,
            "auto_refresh": False,
            "manual_trigger_required": True,
        }
    )

    # Advisory
    advisory: Dict[str, str] = Field(
        default_factory=lambda: {
            "mode": "computed",
            "disclaimer": "Financial data is for informational purposes only.",
        }
    )


class ForecastResponse(BaseModel):
    """
    Response for GET /api/cfo/forecast.

    CONTRACT VERSION: 1
    - cfo_version: ALWAYS present, integer
    - lifecycle: ALWAYS present, explicit state
    - evidence: ALWAYS present, auditability metadata
    """

    # Contract version - ALWAYS present
    cfo_version: int = CFO_CONTRACT_VERSION

    # Lifecycle - ALWAYS present (no inference)
    lifecycle: CFOLifecycle = Field(
        description="Explicit lifecycle state. reason_code required when status != 'success'"
    )

    # Evidence metadata - ALWAYS present (auditability)
    evidence: EvidenceMetadata = Field(
        description="Data sources, coverage window, and freshness"
    )

    ok: bool = True
    request_id: str

    # Organization context
    org_id: str
    generated_at: str

    # Forecast data
    forecasts: ForecastSeries

    # Audit reference
    audit_event_id: Optional[str] = None

    # Guardrails
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "read_only": True,
            "auto_refresh": False,
            "projections_not_facts": True,
            "confidence_threshold": 0.85,
        }
    )

    # Explicit projection disclaimer
    disclaimer: str = Field(
        default="ALL VALUES ARE PROJECTIONS. These forecasts are based on historical data and assumptions. Actual results may differ materially. Do not use as sole basis for financial decisions."
    )


class ExceptionsResponse(BaseModel):
    """
    Response for GET /api/cfo/exceptions.

    CONTRACT VERSION: 1
    - cfo_version: ALWAYS present, integer
    - lifecycle: ALWAYS present, explicit state
    - evidence: ALWAYS present, auditability metadata
    """

    # Contract version - ALWAYS present
    cfo_version: int = CFO_CONTRACT_VERSION

    # Lifecycle - ALWAYS present (no inference)
    lifecycle: CFOLifecycle = Field(
        description="Explicit lifecycle state. reason_code required when status != 'success'"
    )

    # Evidence metadata - ALWAYS present (auditability)
    evidence: EvidenceMetadata = Field(
        description="Data sources, coverage window, and freshness"
    )

    ok: bool = True
    request_id: str

    # Organization context
    org_id: str
    generated_at: str

    # Exceptions
    exceptions: List[FinancialException] = Field(default_factory=list)
    total_count: int = 0
    critical_count: int = 0
    high_count: int = 0

    # Pagination
    limit: int = 50
    offset: int = 0

    # Guardrails
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "read_only": True,
            "detection_only": True,
            "no_auto_remediation": True,
        }
    )

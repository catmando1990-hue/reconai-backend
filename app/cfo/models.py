# app/cfo/models.py
"""
CFO / Financial Controls Models (Phase 3)

Pydantic models for cash flow rollups, burn rate, forecasts, and exceptions.
All projections explicitly labeled as non-factual.

CANONICAL LAWS:
- Projections ≠ facts
- Confidence < 0.85 must be flagged
- Decimal precision for financial data
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional, Dict, Any

from pydantic import BaseModel, Field


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
    """Response for GET /api/cfo/overview."""

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
    """Response for GET /api/cfo/forecast."""

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
    """Response for GET /api/cfo/exceptions."""

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

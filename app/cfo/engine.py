# app/cfo/engine.py
"""
CFO / Financial Controls Engine (Phase 3)

Core engine for cash flow rollups, burn rate, forecasts, and exception detection.
Persists results to separate tables (NO writes to source transactions).

CANONICAL LAWS:
- Backend is source of truth
- No auto-refresh, no background jobs
- Manual-run only
- Immutable audit logging
- Confidence < 0.85 flagged for review
- Projections ≠ facts (explicit labeling)
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from uuid import uuid4

from app.cfo.models import (
    CashFlowRollup,
    BurnRateMetrics,
    ForecastProjection,
    ForecastSeries,
    FinancialException,
    PeriodType,
    TrendDirection,
    ExceptionSeverity,
    ExceptionType,
)


# Confidence threshold for flagging review
CONFIDENCE_THRESHOLD = 0.85

# Outlier detection threshold (z-score)
OUTLIER_Z_THRESHOLD = 2.5


class CFOEngine:
    """
    Engine for CFO financial controls operations.

    All operations are:
    - Manual-run only (no auto-triggers)
    - Read-only on source tables
    - Persisted to separate CFO tables
    - Audit-logged
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create CFO tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # CFO Rollups table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cfo_rollups (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    period_type TEXT NOT NULL,
                    period_label TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    total_inflows REAL NOT NULL DEFAULT 0,
                    revenue_inflows REAL NOT NULL DEFAULT 0,
                    other_inflows REAL NOT NULL DEFAULT 0,
                    total_outflows REAL NOT NULL DEFAULT 0,
                    operating_expenses REAL NOT NULL DEFAULT 0,
                    payroll_expenses REAL NOT NULL DEFAULT 0,
                    other_outflows REAL NOT NULL DEFAULT 0,
                    net_cash_flow REAL NOT NULL DEFAULT 0,
                    transaction_count INTEGER NOT NULL DEFAULT 0,
                    computed_by TEXT NOT NULL,
                    computed_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_rollups_org ON cfo_rollups(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_rollups_period ON cfo_rollups(period_type, period_start)"
            )

            # CFO Forecasts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cfo_forecasts (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    forecast_id TEXT NOT NULL,
                    projection_date TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    projected_cash_balance REAL NOT NULL DEFAULT 0,
                    projected_monthly_burn REAL NOT NULL DEFAULT 0,
                    projected_runway_months REAL,
                    growth_assumption TEXT NOT NULL,
                    assumptions_detail TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    confidence_factors TEXT NOT NULL DEFAULT '[]',
                    requires_review INTEGER NOT NULL DEFAULT 1,
                    computed_by TEXT NOT NULL,
                    computed_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_forecasts_org ON cfo_forecasts(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_forecasts_date ON cfo_forecasts(projection_date)"
            )

            # CFO Exceptions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cfo_exceptions (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    exception_id TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    transaction_id TEXT,
                    description TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    expected_value REAL,
                    actual_value REAL,
                    deviation_pct REAL,
                    z_score REAL,
                    threshold_used REAL,
                    requires_review INTEGER NOT NULL DEFAULT 1,
                    review_priority INTEGER NOT NULL DEFAULT 3,
                    detected_by TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolved_by TEXT,
                    resolved_at TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_exceptions_org ON cfo_exceptions(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_exceptions_severity ON cfo_exceptions(severity)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cfo_exceptions_type ON cfo_exceptions(exception_type)"
            )

            conn.commit()

    # ========================================================================
    # CASH FLOW ROLLUPS
    # ========================================================================

    def compute_cash_flow_rollups(
        self,
        org_id: str,
        user_id: str,
        period_type: PeriodType = "monthly",
        lookback_months: int = 12,
    ) -> List[CashFlowRollup]:
        """
        Compute cash flow rollups for the specified period type.

        Args:
            org_id: Organization ID
            user_id: User ID (for audit)
            period_type: 'monthly' or 'quarterly'
            lookback_months: Number of months to look back

        Returns:
            List of CashFlowRollup objects
        """
        now = datetime.utcnow()
        end_date = date(now.year, now.month, 1) - timedelta(days=1)  # End of last month

        # Calculate start date
        start_date = end_date - timedelta(days=lookback_months * 31)
        start_date = date(start_date.year, start_date.month, 1)

        # Generate period boundaries
        periods = self._generate_periods(start_date, end_date, period_type)

        rollups: List[CashFlowRollup] = []

        for period_start, period_end, period_label in periods:
            rollup = self._compute_period_rollup(
                org_id, period_type, period_start, period_end, period_label
            )
            rollups.append(rollup)

        # Persist rollups
        self._persist_rollups(org_id, user_id, rollups)

        return rollups

    def _generate_periods(
        self, start_date: date, end_date: date, period_type: PeriodType
    ) -> List[Tuple[date, date, str]]:
        """Generate period boundaries based on period type."""
        periods = []
        current = start_date

        while current <= end_date:
            if period_type == "monthly":
                # Month boundaries
                if current.month == 12:
                    period_end = date(current.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
                period_label = current.strftime("%Y-%m")
                next_start = period_end + timedelta(days=1)

            elif period_type == "quarterly":
                # Quarter boundaries
                quarter = (current.month - 1) // 3 + 1
                quarter_end_month = quarter * 3
                if quarter_end_month == 12:
                    period_end = date(current.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end = date(current.year, quarter_end_month + 1, 1) - timedelta(days=1)
                period_label = f"Q{quarter} {current.year}"
                next_start = period_end + timedelta(days=1)

            else:  # yearly
                period_end = date(current.year, 12, 31)
                period_label = str(current.year)
                next_start = date(current.year + 1, 1, 1)

            if period_end > end_date:
                period_end = end_date

            periods.append((current, period_end, period_label))
            current = next_start

        return periods

    def _compute_period_rollup(
        self,
        org_id: str,
        period_type: PeriodType,
        period_start: date,
        period_end: date,
        period_label: str,
    ) -> CashFlowRollup:
        """Compute cash flow rollup for a single period."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Query transactions for this period (READ-ONLY from mvp_transactions)
            query = """
                SELECT
                    id,
                    amount,
                    description,
                    merchant,
                    original_category
                FROM mvp_transactions
                WHERE organization_id = ?
                  AND tx_date >= ?
                  AND tx_date <= ?
            """
            rows = conn.execute(
                query, (org_id, period_start.isoformat(), period_end.isoformat())
            ).fetchall()

        # Categorize transactions
        total_inflows = Decimal("0.00")
        revenue_inflows = Decimal("0.00")
        other_inflows = Decimal("0.00")
        total_outflows = Decimal("0.00")
        operating_expenses = Decimal("0.00")
        payroll_expenses = Decimal("0.00")
        other_outflows = Decimal("0.00")

        for row in rows:
            amount = Decimal(str(row["amount"] or 0))
            category = (row["original_category"] or "").lower()
            description = (row["description"] or "").lower()

            if amount > 0:
                # Inflow
                total_inflows += amount
                if "revenue" in category or "income" in category or "sales" in category:
                    revenue_inflows += amount
                else:
                    other_inflows += amount
            else:
                # Outflow (negative amount)
                outflow = abs(amount)
                total_outflows += outflow

                if "payroll" in category or "salary" in description or "wages" in description:
                    payroll_expenses += outflow
                elif any(kw in category for kw in ["operating", "expense", "cost", "utility"]):
                    operating_expenses += outflow
                else:
                    other_outflows += outflow

        net_cash_flow = total_inflows - total_outflows

        return CashFlowRollup(
            period_type=period_type,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            total_inflows=total_inflows,
            revenue_inflows=revenue_inflows,
            other_inflows=other_inflows,
            total_outflows=total_outflows,
            operating_expenses=operating_expenses,
            payroll_expenses=payroll_expenses,
            other_outflows=other_outflows,
            net_cash_flow=net_cash_flow,
            transaction_count=len(rows),
        )

    def _persist_rollups(
        self, org_id: str, user_id: str, rollups: List[CashFlowRollup]
    ) -> None:
        """Persist rollups to cfo_rollups table."""
        if not rollups:
            return

        now = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for rollup in rollups:
                conn.execute(
                    """
                    INSERT INTO cfo_rollups (
                        id, organization_id, period_type, period_label,
                        period_start, period_end, total_inflows, revenue_inflows,
                        other_inflows, total_outflows, operating_expenses,
                        payroll_expenses, other_outflows, net_cash_flow,
                        transaction_count, computed_by, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        org_id,
                        rollup.period_type,
                        rollup.period_label,
                        rollup.period_start.isoformat(),
                        rollup.period_end.isoformat(),
                        float(rollup.total_inflows),
                        float(rollup.revenue_inflows),
                        float(rollup.other_inflows),
                        float(rollup.total_outflows),
                        float(rollup.operating_expenses),
                        float(rollup.payroll_expenses),
                        float(rollup.other_outflows),
                        float(rollup.net_cash_flow),
                        rollup.transaction_count,
                        user_id,
                        now,
                    ),
                )
            conn.commit()

    # ========================================================================
    # BURN RATE CALCULATION
    # ========================================================================

    def calculate_burn_rate(
        self,
        org_id: str,
        lookback_days: int = 90,
    ) -> BurnRateMetrics:
        """
        Calculate burn rate from historical transactions.

        Args:
            org_id: Organization ID
            lookback_days: Number of days to analyze

        Returns:
            BurnRateMetrics object
        """
        now = datetime.utcnow()
        start_date = (now - timedelta(days=lookback_days)).date()
        end_date = now.date()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get transactions for the period (READ-ONLY)
            query = """
                SELECT amount, tx_date
                FROM mvp_transactions
                WHERE organization_id = ?
                  AND tx_date >= ?
                  AND tx_date <= ?
                ORDER BY tx_date
            """
            rows = conn.execute(
                query, (org_id, start_date.isoformat(), end_date.isoformat())
            ).fetchall()

            # Get current cash balance estimate
            balance_query = """
                SELECT SUM(amount) as balance
                FROM mvp_transactions
                WHERE organization_id = ?
            """
            balance_row = conn.execute(balance_query, (org_id,)).fetchone()
            current_balance = Decimal(str(balance_row["balance"] or 0))

        if not rows:
            return BurnRateMetrics(
                current_cash_balance=current_balance,
                calculation_period_days=lookback_days,
                data_points_used=0,
                confidence=0.3,
                requires_review=True,
            )

        # Calculate total outflows
        total_outflows = Decimal("0.00")
        monthly_outflows: Dict[str, Decimal] = {}

        for row in rows:
            amount = Decimal(str(row["amount"] or 0))
            if amount < 0:
                outflow = abs(amount)
                total_outflows += outflow

                # Group by month for trend analysis
                tx_date = row["tx_date"][:7] if row["tx_date"] else "unknown"
                monthly_outflows[tx_date] = monthly_outflows.get(tx_date, Decimal("0.00")) + outflow

        # Calculate rates
        days_in_period = lookback_days
        daily_burn = total_outflows / days_in_period if days_in_period > 0 else Decimal("0.00")
        weekly_burn = daily_burn * 7
        monthly_burn = daily_burn * 30

        # Calculate trend
        burn_trend, trend_pct = self._calculate_burn_trend(monthly_outflows)

        # Calculate runway
        runway_months = None
        runway_weeks = None
        if monthly_burn > 0 and current_balance > 0:
            runway_months = current_balance / monthly_burn
            runway_weeks = current_balance / weekly_burn if weekly_burn > 0 else None

        # Calculate confidence
        confidence = self._calculate_burn_confidence(len(rows), lookback_days, monthly_outflows)

        return BurnRateMetrics(
            current_cash_balance=current_balance,
            monthly_burn_rate=monthly_burn,
            weekly_burn_rate=weekly_burn,
            daily_burn_rate=daily_burn,
            burn_trend=burn_trend,
            burn_trend_pct_change=trend_pct,
            runway_months=runway_months,
            runway_weeks=runway_weeks,
            calculation_period_days=lookback_days,
            data_points_used=len(rows),
            confidence=confidence,
            requires_review=confidence < CONFIDENCE_THRESHOLD,
        )

    def _calculate_burn_trend(
        self, monthly_outflows: Dict[str, Decimal]
    ) -> Tuple[TrendDirection, Decimal]:
        """Calculate burn rate trend direction."""
        if len(monthly_outflows) < 2:
            return "unknown", Decimal("0.00")

        sorted_months = sorted(monthly_outflows.keys())
        if len(sorted_months) < 2:
            return "unknown", Decimal("0.00")

        # Compare last two months
        recent = monthly_outflows[sorted_months[-1]]
        previous = monthly_outflows[sorted_months[-2]]

        if previous == 0:
            return "unknown", Decimal("0.00")

        pct_change = ((recent - previous) / previous) * 100

        if pct_change > 10:
            return "accelerating", pct_change
        elif pct_change < -10:
            return "improving", pct_change
        else:
            return "stable", pct_change

    def _calculate_burn_confidence(
        self,
        data_points: int,
        lookback_days: int,
        monthly_outflows: Dict[str, Decimal],
    ) -> float:
        """Calculate confidence score for burn rate calculation."""
        confidence = 0.5  # Base confidence

        # More data points = higher confidence
        if data_points >= 100:
            confidence += 0.2
        elif data_points >= 50:
            confidence += 0.15
        elif data_points >= 20:
            confidence += 0.1

        # More months of data = higher confidence
        months_of_data = len(monthly_outflows)
        if months_of_data >= 6:
            confidence += 0.15
        elif months_of_data >= 3:
            confidence += 0.1

        # Consistency of data (low variance = higher confidence)
        if months_of_data >= 2:
            values = [float(v) for v in monthly_outflows.values()]
            if len(values) >= 2:
                mean = statistics.mean(values)
                if mean > 0:
                    cv = statistics.stdev(values) / mean  # Coefficient of variation
                    if cv < 0.3:
                        confidence += 0.1
                    elif cv < 0.5:
                        confidence += 0.05

        return min(confidence, 0.95)

    # ========================================================================
    # FORECAST PROJECTIONS
    # ========================================================================

    def generate_forecast(
        self,
        org_id: str,
        user_id: str,
        horizon_days: int = 90,
        projection_intervals: List[int] = None,
    ) -> Tuple[ForecastSeries, str]:
        """
        Generate forecast projections.

        IMPORTANT: All projections are labeled as NON-FACTUAL.
        Confidence < 0.85 is flagged for review.

        Args:
            org_id: Organization ID
            user_id: User ID (for audit)
            horizon_days: Maximum forecast horizon
            projection_intervals: Days at which to project (default: 30, 60, 90)

        Returns:
            (ForecastSeries, audit_event_id)
        """
        if projection_intervals is None:
            projection_intervals = [30, 60, 90]

        # Get current burn rate
        burn_rate = self.calculate_burn_rate(org_id)

        # Generate projections
        forecasts: List[ForecastProjection] = []
        now = datetime.utcnow()

        for days in projection_intervals:
            if days > horizon_days:
                continue

            projection = self._generate_single_projection(
                org_id, burn_rate, days, now
            )
            forecasts.append(projection)

        # Calculate overall confidence
        confidences = [f.confidence for f in forecasts] if forecasts else [0.5]
        overall_confidence = statistics.mean(confidences)
        min_confidence = min(confidences)
        max_confidence = max(confidences)

        forecast_series = ForecastSeries(
            forecasts=forecasts,
            overall_confidence=overall_confidence,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            historical_data_points=burn_rate.data_points_used,
            historical_period_days=burn_rate.calculation_period_days,
            all_values_are_projections=True,  # ALWAYS True
        )

        # Persist forecasts
        audit_id = self._persist_forecasts(org_id, user_id, forecasts)

        return forecast_series, audit_id

    def _generate_single_projection(
        self,
        org_id: str,
        burn_rate: BurnRateMetrics,
        days_ahead: int,
        now: datetime,
    ) -> ForecastProjection:
        """Generate a single forecast projection."""
        projection_date = (now + timedelta(days=days_ahead)).date()

        # Simple linear projection
        daily_burn = burn_rate.daily_burn_rate
        projected_cash = burn_rate.current_cash_balance - (daily_burn * days_ahead)

        # Adjust for uncertainty over time
        # Confidence decreases with horizon
        base_confidence = burn_rate.confidence
        horizon_penalty = min(days_ahead / 365, 0.3)  # Max 30% penalty
        confidence = max(base_confidence - horizon_penalty, 0.3)

        # Calculate projected runway
        projected_runway = None
        if burn_rate.monthly_burn_rate > 0 and projected_cash > 0:
            projected_runway = projected_cash / burn_rate.monthly_burn_rate

        # Confidence factors
        confidence_factors = []
        if burn_rate.data_points_used < 50:
            confidence_factors.append("Limited historical data")
        if days_ahead > 60:
            confidence_factors.append("Extended forecast horizon increases uncertainty")
        if burn_rate.burn_trend == "accelerating":
            confidence_factors.append("Burn rate trend is accelerating")
        if burn_rate.burn_trend == "unknown":
            confidence_factors.append("Insufficient data for trend analysis")

        return ForecastProjection(
            forecast_id=f"fcst_{uuid4().hex[:12]}",
            projection_date=projection_date,
            horizon_days=days_ahead,
            projected_cash_balance=max(projected_cash, Decimal("0.00")),
            projected_monthly_burn=burn_rate.monthly_burn_rate,
            projected_runway_months=projected_runway,
            growth_assumption="linear",
            assumptions_detail={
                "model": "linear_extrapolation",
                "daily_burn_rate": float(daily_burn),
                "trend_direction": burn_rate.burn_trend,
                "data_points": burn_rate.data_points_used,
            },
            confidence=confidence,
            confidence_factors=confidence_factors,
            requires_review=confidence < CONFIDENCE_THRESHOLD,
            is_projection=True,  # ALWAYS True
            projection_disclaimer="This is a PROJECTION based on historical data. Actual results may vary significantly.",
        )

    def _persist_forecasts(
        self, org_id: str, user_id: str, forecasts: List[ForecastProjection]
    ) -> str:
        """Persist forecasts to cfo_forecasts table."""
        audit_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for forecast in forecasts:
                conn.execute(
                    """
                    INSERT INTO cfo_forecasts (
                        id, organization_id, forecast_id, projection_date,
                        horizon_days, projected_cash_balance, projected_monthly_burn,
                        projected_runway_months, growth_assumption, assumptions_detail,
                        confidence, confidence_factors, requires_review,
                        computed_by, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        org_id,
                        forecast.forecast_id,
                        forecast.projection_date.isoformat(),
                        forecast.horizon_days,
                        float(forecast.projected_cash_balance),
                        float(forecast.projected_monthly_burn),
                        float(forecast.projected_runway_months) if forecast.projected_runway_months else None,
                        forecast.growth_assumption,
                        json.dumps(forecast.assumptions_detail),
                        forecast.confidence,
                        json.dumps(forecast.confidence_factors),
                        1 if forecast.requires_review else 0,
                        user_id,
                        now,
                    ),
                )
            conn.commit()

        return audit_id

    # ========================================================================
    # EXCEPTION DETECTION
    # ========================================================================

    def detect_exceptions(
        self,
        org_id: str,
        user_id: str,
        lookback_days: int = 90,
    ) -> List[FinancialException]:
        """
        Detect financial exceptions (outliers only).

        Args:
            org_id: Organization ID
            user_id: User ID (for audit)
            lookback_days: Days to analyze

        Returns:
            List of FinancialException objects
        """
        now = datetime.utcnow()
        start_date = (now - timedelta(days=lookback_days)).date()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get transactions (READ-ONLY)
            query = """
                SELECT id, amount, description, merchant, original_category, tx_date
                FROM mvp_transactions
                WHERE organization_id = ?
                  AND tx_date >= ?
                ORDER BY tx_date DESC
            """
            rows = conn.execute(query, (org_id, start_date.isoformat())).fetchall()

        if not rows:
            return []

        exceptions: List[FinancialException] = []

        # Detect amount outliers
        amount_exceptions = self._detect_amount_outliers(rows)
        exceptions.extend(amount_exceptions)

        # Detect frequency anomalies
        frequency_exceptions = self._detect_frequency_anomalies(rows)
        exceptions.extend(frequency_exceptions)

        # Persist exceptions
        self._persist_exceptions(org_id, user_id, exceptions)

        return exceptions

    def _detect_amount_outliers(
        self, rows: List[sqlite3.Row]
    ) -> List[FinancialException]:
        """Detect transactions with unusual amounts."""
        exceptions = []

        # Calculate statistics
        amounts = [abs(float(row["amount"] or 0)) for row in rows if row["amount"]]
        if len(amounts) < 5:
            return []

        mean_amount = statistics.mean(amounts)
        stdev_amount = statistics.stdev(amounts) if len(amounts) > 1 else 0

        if stdev_amount == 0:
            return []

        for row in rows:
            amount = abs(float(row["amount"] or 0))
            z_score = (amount - mean_amount) / stdev_amount

            if abs(z_score) > OUTLIER_Z_THRESHOLD:
                severity = self._determine_severity(z_score)
                expected = Decimal(str(mean_amount))
                actual = Decimal(str(amount))
                deviation = ((actual - expected) / expected * 100) if expected > 0 else Decimal("0")

                exceptions.append(
                    FinancialException(
                        exception_id=f"exc_{uuid4().hex[:12]}",
                        exception_type="amount_outlier",
                        severity=severity,
                        transaction_id=row["id"],
                        description=f"Unusual transaction amount: ${amount:,.2f}",
                        explanation=f"Amount is {abs(z_score):.1f} standard deviations from mean (${mean_amount:,.2f})",
                        expected_value=expected,
                        actual_value=actual,
                        deviation_pct=deviation,
                        z_score=z_score,
                        threshold_used=OUTLIER_Z_THRESHOLD,
                        requires_review=True,
                        review_priority=2 if severity == "critical" else 3,
                    )
                )

        return exceptions

    def _detect_frequency_anomalies(
        self, rows: List[sqlite3.Row]
    ) -> List[FinancialException]:
        """Detect unusual transaction frequency patterns."""
        exceptions = []

        # Group by merchant
        merchant_counts: Dict[str, int] = {}
        for row in rows:
            merchant = row["merchant"] or "Unknown"
            merchant_counts[merchant] = merchant_counts.get(merchant, 0) + 1

        if len(merchant_counts) < 3:
            return []

        # Calculate statistics
        counts = list(merchant_counts.values())
        mean_count = statistics.mean(counts)
        stdev_count = statistics.stdev(counts) if len(counts) > 1 else 0

        if stdev_count == 0:
            return []

        for merchant, count in merchant_counts.items():
            z_score = (count - mean_count) / stdev_count

            if z_score > OUTLIER_Z_THRESHOLD:  # Only flag high frequency
                severity = self._determine_severity(z_score)

                exceptions.append(
                    FinancialException(
                        exception_id=f"exc_{uuid4().hex[:12]}",
                        exception_type="frequency_anomaly",
                        severity=severity,
                        transaction_id=None,
                        description=f"Unusual transaction frequency for {merchant}",
                        explanation=f"{count} transactions from this merchant ({z_score:.1f} std devs above mean of {mean_count:.1f})",
                        expected_value=Decimal(str(mean_count)),
                        actual_value=Decimal(str(count)),
                        deviation_pct=Decimal(str(((count - mean_count) / mean_count * 100) if mean_count > 0 else 0)),
                        z_score=z_score,
                        threshold_used=OUTLIER_Z_THRESHOLD,
                        requires_review=True,
                        review_priority=3,
                    )
                )

        return exceptions

    def _determine_severity(self, z_score: float) -> ExceptionSeverity:
        """Determine exception severity based on z-score."""
        abs_z = abs(z_score)
        if abs_z > 4:
            return "critical"
        elif abs_z > 3:
            return "high"
        elif abs_z > 2.5:
            return "medium"
        else:
            return "low"

    def _persist_exceptions(
        self, org_id: str, user_id: str, exceptions: List[FinancialException]
    ) -> None:
        """Persist exceptions to cfo_exceptions table."""
        if not exceptions:
            return

        now = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for exc in exceptions:
                conn.execute(
                    """
                    INSERT INTO cfo_exceptions (
                        id, organization_id, exception_id, exception_type,
                        severity, transaction_id, description, explanation,
                        expected_value, actual_value, deviation_pct,
                        z_score, threshold_used, requires_review,
                        review_priority, detected_by, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        org_id,
                        exc.exception_id,
                        exc.exception_type,
                        exc.severity,
                        exc.transaction_id,
                        exc.description,
                        exc.explanation,
                        float(exc.expected_value) if exc.expected_value else None,
                        float(exc.actual_value) if exc.actual_value else None,
                        float(exc.deviation_pct) if exc.deviation_pct else None,
                        exc.z_score,
                        exc.threshold_used,
                        1 if exc.requires_review else 0,
                        exc.review_priority,
                        user_id,
                        now,
                    ),
                )
            conn.commit()

    # ========================================================================
    # QUERY METHODS (READ-ONLY)
    # ========================================================================

    def get_recent_rollups(
        self,
        org_id: str,
        period_type: PeriodType = "monthly",
        limit: int = 12,
    ) -> List[CashFlowRollup]:
        """Get most recent rollups from cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM cfo_rollups
                WHERE organization_id = ? AND period_type = ?
                ORDER BY period_start DESC
                LIMIT ?
                """,
                (org_id, period_type, limit),
            ).fetchall()

        return [
            CashFlowRollup(
                period_type=row["period_type"],
                period_label=row["period_label"],
                period_start=date.fromisoformat(row["period_start"]),
                period_end=date.fromisoformat(row["period_end"]),
                total_inflows=Decimal(str(row["total_inflows"])),
                revenue_inflows=Decimal(str(row["revenue_inflows"])),
                other_inflows=Decimal(str(row["other_inflows"])),
                total_outflows=Decimal(str(row["total_outflows"])),
                operating_expenses=Decimal(str(row["operating_expenses"])),
                payroll_expenses=Decimal(str(row["payroll_expenses"])),
                other_outflows=Decimal(str(row["other_outflows"])),
                net_cash_flow=Decimal(str(row["net_cash_flow"])),
                transaction_count=row["transaction_count"],
                computed_at=row["computed_at"],
            )
            for row in rows
        ]

    def get_recent_exceptions(
        self,
        org_id: str,
        limit: int = 50,
        offset: int = 0,
        severity: Optional[ExceptionSeverity] = None,
        unresolved_only: bool = True,
    ) -> Tuple[List[FinancialException], int]:
        """Get recent exceptions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            where_clauses = ["organization_id = ?"]
            params: List[Any] = [org_id]

            if unresolved_only:
                where_clauses.append("resolved = 0")

            if severity:
                where_clauses.append("severity = ?")
                params.append(severity)

            where_sql = " AND ".join(where_clauses)

            # Count
            count = conn.execute(
                f"SELECT COUNT(*) as cnt FROM cfo_exceptions WHERE {where_sql}",
                params,
            ).fetchone()["cnt"]

            # Data
            rows = conn.execute(
                f"""
                SELECT * FROM cfo_exceptions
                WHERE {where_sql}
                ORDER BY review_priority ASC, detected_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()

        exceptions = [
            FinancialException(
                exception_id=row["exception_id"],
                exception_type=row["exception_type"],
                severity=row["severity"],
                transaction_id=row["transaction_id"],
                description=row["description"],
                explanation=row["explanation"],
                expected_value=Decimal(str(row["expected_value"])) if row["expected_value"] else None,
                actual_value=Decimal(str(row["actual_value"])) if row["actual_value"] else None,
                deviation_pct=Decimal(str(row["deviation_pct"])) if row["deviation_pct"] else None,
                z_score=row["z_score"],
                threshold_used=row["threshold_used"],
                requires_review=bool(row["requires_review"]),
                review_priority=row["review_priority"],
                detected_at=row["detected_at"],
            )
            for row in rows
        ]

        return exceptions, count

# app/tax_intelligence/engine.py

from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
import uuid

from app.tax_intelligence.models import (
    TaxEstimate,
    QuarterlyTaxPayment,
    TaxQuarter,
    DeductionOptimization,
    DeductionCategory,
    TaxCalendar,
    TaxDeadline,
    DeadlineType,
    TaxProjection,
    StateFilingRequirement,
    FEDERAL_TAX_BRACKETS_2024_SINGLE,
    FEDERAL_TAX_BRACKETS_2024_MARRIED,
    SELF_EMPLOYMENT_TAX_RATE,
    SELF_EMPLOYMENT_DEDUCTION_RATE,
    SOCIAL_SECURITY_WAGE_BASE,
    STANDARD_DEDUCTION_2024,
)
from app.financial_reports.engine import FinancialReportsEngine


class TaxIntelligenceEngine:
    """
    Tax Intelligence Engine for ReconAI.

    Provides:
    - Quarterly tax estimates
    - Deduction optimization
    - Tax deadline tracking
    - State-specific tax rules
    - Tax projections
    """

    def __init__(self, reports_engine: FinancialReportsEngine):
        self.reports = reports_engine

    # ========================================================================
    # QUARTERLY TAX ESTIMATES
    # ========================================================================

    def calculate_quarterly_estimates(
        self,
        organization_id: str,
        tax_year: int,
        filing_status: str = "Single",
        business_type: str = "Schedule C",
        state_code: Optional[str] = None
    ) -> TaxEstimate:
        """
        Calculate quarterly estimated tax payments for the year.

        Uses current year-to-date data to project annual income and
        calculates required quarterly payments.
        """
        estimate = TaxEstimate(
            tax_year=tax_year,
            organization_id=organization_id,
            business_type=business_type,
            filing_status=filing_status
        )

        # Get P&L for the year to date
        today = date.today()
        year_start = date(tax_year, 1, 1)
        year_end = date(tax_year, 12, 31)

        # If future year, use projections; if past, use actuals
        if tax_year > today.year:
            # Future year - use last year's data as baseline
            pl_report = self.reports.generate_profit_loss(
                organization_id,
                date(tax_year - 1, 1, 1),
                date(tax_year - 1, 12, 31)
            )
        elif tax_year < today.year:
            # Past year - use full year actuals
            pl_report = self.reports.generate_profit_loss(
                organization_id,
                year_start,
                year_end
            )
        else:
            # Current year - use YTD and project
            ytd_end = min(today, year_end)
            pl_report = self.reports.generate_profit_loss(
                organization_id,
                year_start,
                ytd_end
            )

            # Project to full year
            days_elapsed = (ytd_end - year_start).days + 1
            days_in_year = (year_end - year_start).days + 1
            projection_factor = Decimal(str(days_in_year / days_elapsed))

            pl_report.total_revenue = pl_report.total_revenue * projection_factor
            pl_report.net_income = pl_report.net_income * projection_factor

        # Annual income calculations
        estimate.total_gross_income = pl_report.total_revenue

        # Standard deduction
        standard_deduction = STANDARD_DEDUCTION_2024.get(filing_status, Decimal("14600"))

        # Business deductions (from P&L)
        business_deductions = (
            pl_report.cost_of_goods_sold +
            pl_report.total_operating_expenses +
            pl_report.other_expenses
        )

        # Self-employment tax deduction (employer portion)
        se_tax = self._calculate_self_employment_tax(pl_report.net_income)
        se_tax_deduction = se_tax * Decimal("0.50")  # Deduct employer portion

        estimate.total_deductions = business_deductions + standard_deduction + se_tax_deduction
        estimate.total_taxable_income = max(
            Decimal("0.00"),
            estimate.total_gross_income - estimate.total_deductions
        )

        # Calculate taxes
        estimate.total_federal_tax = self._calculate_federal_income_tax(
            estimate.total_taxable_income,
            filing_status
        )
        estimate.total_self_employment_tax = se_tax

        # State tax (if applicable)
        if state_code:
            state_req = self._get_state_filing_requirement(state_code)
            if state_req.has_state_income_tax and state_req.state_tax_rate:
                estimate.total_state_tax = estimate.total_taxable_income * state_req.state_tax_rate

        estimate.total_tax_liability = (
            estimate.total_federal_tax +
            estimate.total_self_employment_tax +
            estimate.total_state_tax
        )

        # Calculate effective and marginal rates
        if estimate.total_gross_income > 0:
            estimate.effective_tax_rate = (
                estimate.total_tax_liability / estimate.total_gross_income
            ) * 100

        estimate.marginal_tax_rate = self._get_marginal_tax_rate(
            estimate.total_taxable_income,
            filing_status
        ) * 100

        # Generate quarterly payments
        estimate.quarterly_payments = self._generate_quarterly_payments(
            tax_year,
            estimate.total_tax_liability
        )

        return estimate

    def _calculate_federal_income_tax(
        self,
        taxable_income: Decimal,
        filing_status: str
    ) -> Decimal:
        """Calculate federal income tax using progressive brackets."""
        if filing_status == "Married Filing Jointly":
            brackets = FEDERAL_TAX_BRACKETS_2024_MARRIED
        else:
            brackets = FEDERAL_TAX_BRACKETS_2024_SINGLE

        total_tax = Decimal("0.00")

        for bracket in brackets:
            if taxable_income <= bracket.min_income:
                break

            # Calculate taxable amount in this bracket
            if bracket.max_income is None:
                # Top bracket - all remaining income
                bracket_income = taxable_income - bracket.min_income
            else:
                # Calculate income in this bracket
                bracket_income = min(
                    taxable_income - bracket.min_income,
                    bracket.max_income - bracket.min_income
                )

            total_tax += bracket_income * bracket.rate

        return total_tax

    def _calculate_self_employment_tax(self, net_income: Decimal) -> Decimal:
        """Calculate self-employment tax (Social Security + Medicare)."""
        if net_income <= 0:
            return Decimal("0.00")

        # Apply deduction for employer portion
        taxable_se_income = net_income * SELF_EMPLOYMENT_DEDUCTION_RATE

        # Social Security tax (up to wage base limit)
        ss_income = min(taxable_se_income, SOCIAL_SECURITY_WAGE_BASE)
        ss_tax = ss_income * Decimal("0.124")  # 12.4%

        # Medicare tax (no limit)
        medicare_tax = taxable_se_income * Decimal("0.029")  # 2.9%

        return ss_tax + medicare_tax

    def _get_marginal_tax_rate(
        self,
        taxable_income: Decimal,
        filing_status: str
    ) -> Decimal:
        """Get marginal (top) tax rate for the given income."""
        if filing_status == "Married Filing Jointly":
            brackets = FEDERAL_TAX_BRACKETS_2024_MARRIED
        else:
            brackets = FEDERAL_TAX_BRACKETS_2024_SINGLE

        for bracket in reversed(brackets):
            if taxable_income >= bracket.min_income:
                return bracket.rate

        return Decimal("0.00")

    def _generate_quarterly_payments(
        self,
        tax_year: int,
        total_tax_liability: Decimal
    ) -> List[QuarterlyTaxPayment]:
        """Generate quarterly payment schedule."""
        quarterly_amount = total_tax_liability / 4

        quarters = [
            (TaxQuarter.Q1, date(tax_year, 4, 15)),
            (TaxQuarter.Q2, date(tax_year, 6, 15)),
            (TaxQuarter.Q3, date(tax_year, 9, 15)),
            (TaxQuarter.Q4, date(tax_year + 1, 1, 15)),
        ]

        payments = []
        for quarter, due_date in quarters:
            payment = QuarterlyTaxPayment(
                quarter=quarter,
                tax_year=tax_year,
                due_date=due_date,
                total_tax_due=quarterly_amount
            )
            payments.append(payment)

        return payments

    # ========================================================================
    # DEDUCTION OPTIMIZATION
    # ========================================================================

    def optimize_deductions(
        self,
        organization_id: str,
        tax_year: int,
        marginal_tax_rate: Optional[Decimal] = None
    ) -> DeductionOptimization:
        """
        Analyze expenses and recommend deduction optimizations.

        Identifies:
        - Underutilized deductions
        - Missed deductions
        - Deduction timing strategies
        - Documentation gaps
        """
        if marginal_tax_rate is None:
            marginal_tax_rate = Decimal("0.24")  # Default to 24% bracket

        optimization = DeductionOptimization(
            tax_year=tax_year,
            organization_id=organization_id,
            as_of_date=date.today()
        )

        # Get P&L for the year
        year_start = date(tax_year, 1, 1)
        year_end = date(tax_year, 12, 31)

        pl_report = self.reports.generate_profit_loss(
            organization_id,
            year_start,
            min(year_end, date.today())
        )

        # Analyze expense categories
        for expense_category in pl_report.operating_expenses_breakdown:
            category = DeductionCategory(
                category_name=expense_category.category_name,
                total_expenses=expense_category.amount,
                deductible_amount=expense_category.amount,  # Assume 100% for now
                deduction_rate=Decimal("1.00")
            )

            # Calculate tax savings
            category.tax_savings = category.deductible_amount * marginal_tax_rate

            # Add recommendations based on category
            category.recommendations = self._get_deduction_recommendations(
                expense_category.category_name,
                expense_category.amount
            )

            optimization.categories.append(category)
            optimization.total_expenses += category.total_expenses
            optimization.total_deductions += category.deductible_amount

        # Common missed deductions
        optimization.commonly_missed = [
            "Home office deduction (if applicable)",
            "Business use of vehicle (mileage or actual expenses)",
            "Health insurance premiums (self-employed)",
            "Retirement plan contributions (SEP-IRA, Solo 401k)",
            "Business insurance premiums",
            "Professional development and training",
            "Business meals (50% deductible)",
            "Depreciation on equipment and assets",
            "Software subscriptions and SaaS tools",
            "Bank fees and credit card processing fees",
        ]

        # Top recommendations
        optimization.top_recommendations = [
            "Maximize retirement contributions to reduce taxable income",
            "Track all business mileage for vehicle deduction",
            "Document home office square footage for deduction",
            "Keep detailed records of business meals and entertainment",
            "Consider Section 179 expensing for equipment purchases",
        ]

        # Calculate potential tax savings
        optimization.potential_tax_savings = (
            optimization.potential_additional_deductions * marginal_tax_rate
        )

        return optimization

    def _get_deduction_recommendations(
        self,
        category_name: str,
        amount: Decimal
    ) -> List[str]:
        """Get deduction recommendations for a category."""
        recommendations = []
        category_lower = category_name.lower()

        if "travel" in category_lower:
            recommendations.append("Track mileage for all business travel")
            recommendations.append("Keep receipts for lodging and meals")

        elif "office" in category_lower:
            recommendations.append("Consider home office deduction if you have dedicated space")
            recommendations.append("Keep receipts for office supplies and equipment")

        elif "meal" in category_lower or "entertainment" in category_lower:
            recommendations.append("Remember: Business meals are 50% deductible")
            recommendations.append("Document business purpose of each meal")

        elif "insurance" in category_lower:
            recommendations.append("Health insurance premiums are 100% deductible for self-employed")

        elif "vehicle" in category_lower or "auto" in category_lower:
            recommendations.append("Track business vs. personal mileage")
            recommendations.append("Consider standard mileage vs. actual expense method")

        return recommendations

    # ========================================================================
    # TAX CALENDAR & DEADLINES
    # ========================================================================

    def get_tax_calendar(
        self,
        organization_id: str,
        tax_year: int,
        business_type: str = "Schedule C",
        state_code: Optional[str] = None
    ) -> TaxCalendar:
        """
        Get tax calendar with all filing deadlines.

        Includes:
        - Quarterly estimated payments
        - Annual filing deadlines
        - Form 1099 deadlines
        - State-specific deadlines
        """
        calendar = TaxCalendar(
            tax_year=tax_year,
            organization_id=organization_id,
            business_type=business_type,
            state=state_code
        )

        # Quarterly estimated payment deadlines
        quarters = [
            (TaxQuarter.Q1, date(tax_year, 4, 15), "Q1 Estimated Tax Payment"),
            (TaxQuarter.Q2, date(tax_year, 6, 15), "Q2 Estimated Tax Payment"),
            (TaxQuarter.Q3, date(tax_year, 9, 15), "Q3 Estimated Tax Payment"),
            (TaxQuarter.Q4, date(tax_year + 1, 1, 15), "Q4 Estimated Tax Payment"),
        ]

        for quarter, due_date, description in quarters:
            deadline = TaxDeadline(
                deadline_id=str(uuid.uuid4()),
                deadline_type=DeadlineType.QUARTERLY_ESTIMATE,
                description=description,
                due_date=due_date,
                tax_year=tax_year,
                quarter=quarter,
                form_number="1040-ES"
            )
            calendar.deadlines.append(deadline)

        # Annual filing deadline
        annual_deadline = TaxDeadline(
            deadline_id=str(uuid.uuid4()),
            deadline_type=DeadlineType.ANNUAL_FILING,
            description=f"{tax_year} Tax Return Filing Deadline",
            due_date=date(tax_year + 1, 4, 15),
            tax_year=tax_year,
            form_number="1040 Schedule C"
        )
        calendar.deadlines.append(annual_deadline)

        # Extension deadline (if needed)
        extension_deadline = TaxDeadline(
            deadline_id=str(uuid.uuid4()),
            deadline_type=DeadlineType.EXTENSION,
            description=f"{tax_year} Extended Filing Deadline",
            due_date=date(tax_year + 1, 10, 15),
            tax_year=tax_year,
            form_number="4868"
        )
        calendar.deadlines.append(extension_deadline)

        # 1099 deadlines (if business has contractors)
        form_1099_deadline = TaxDeadline(
            deadline_id=str(uuid.uuid4()),
            deadline_type=DeadlineType.FORM_1099,
            description=f"{tax_year} Form 1099 Distribution Deadline",
            due_date=date(tax_year + 1, 1, 31),
            tax_year=tax_year,
            form_number="1099-NEC"
        )
        calendar.deadlines.append(form_1099_deadline)

        # State deadlines
        if state_code:
            state_req = self._get_state_filing_requirement(state_code)
            if state_req.has_state_income_tax and state_req.filing_deadline:
                state_deadline = TaxDeadline(
                    deadline_id=str(uuid.uuid4()),
                    deadline_type=DeadlineType.ANNUAL_FILING,
                    description=f"{state_req.state_name} State Tax Return",
                    due_date=state_req.filing_deadline,
                    tax_year=tax_year
                )
                calendar.deadlines.append(state_deadline)

        # Count upcoming and overdue
        today = date.today()
        ninety_days_out = today + timedelta(days=90)

        for deadline in calendar.deadlines:
            if not deadline.is_completed:
                if deadline.due_date < today:
                    calendar.overdue_count += 1
                elif deadline.due_date <= ninety_days_out:
                    calendar.upcoming_count += 1

        return calendar

    # ========================================================================
    # TAX PROJECTIONS
    # ========================================================================

    def project_year_end_taxes(
        self,
        organization_id: str,
        tax_year: int,
        filing_status: str = "Single"
    ) -> TaxProjection:
        """
        Project year-end tax liability based on YTD performance.

        Helps with:
        - Cash flow planning
        - Q4 estimated payment calculation
        - Year-end tax strategy
        """
        projection = TaxProjection(
            organization_id=organization_id,
            projection_date=date.today(),
            tax_year=tax_year
        )

        # Get YTD P&L
        year_start = date(tax_year, 1, 1)
        today = date.today()

        pl_ytd = self.reports.generate_profit_loss(
            organization_id,
            year_start,
            today
        )

        projection.ytd_income = pl_ytd.total_revenue
        projection.ytd_expenses = pl_ytd.total_revenue - pl_ytd.net_income
        projection.ytd_net_income = pl_ytd.net_income

        # Project full year
        days_elapsed = (today - year_start).days + 1
        days_in_year = 365
        months_elapsed = today.month
        months_remaining = 12 - months_elapsed

        # Simple linear projection
        if months_elapsed > 0:
            monthly_avg_income = projection.ytd_income / months_elapsed
            monthly_avg_expenses = projection.ytd_expenses / months_elapsed

            projection.projected_annual_income = (
                projection.ytd_income +
                (monthly_avg_income * months_remaining)
            )
            projection.projected_annual_expenses = (
                projection.ytd_expenses +
                (monthly_avg_expenses * months_remaining)
            )

        projection.projected_annual_net_income = (
            projection.projected_annual_income -
            projection.projected_annual_expenses
        )

        # Calculate projected taxes
        projection.projected_federal_tax = self._calculate_federal_income_tax(
            projection.projected_annual_net_income,
            filing_status
        )
        projection.projected_self_employment_tax = self._calculate_self_employment_tax(
            projection.projected_annual_net_income
        )

        projection.projected_total_tax = (
            projection.projected_federal_tax +
            projection.projected_self_employment_tax +
            projection.projected_state_tax
        )

        # Calculate remaining liability
        # Assume 75% paid in Q1-Q3 estimates
        projection.taxes_paid_ytd = projection.projected_total_tax * Decimal("0.75")
        projection.remaining_tax_liability = (
            projection.projected_total_tax - projection.taxes_paid_ytd
        )

        projection.recommended_q4_payment = projection.remaining_tax_liability

        # Cash reserve recommendation (1.2x remaining tax liability for safety)
        projection.cash_reserve_needed = projection.remaining_tax_liability * Decimal("1.2")

        return projection

    # ========================================================================
    # STATE-SPECIFIC RULES
    # ========================================================================

    def _get_state_filing_requirement(self, state_code: str) -> StateFilingRequirement:
        """Get state-specific filing requirements."""
        # Simplified - in production, would fetch from database or config
        state_rules = {
            "CA": StateFilingRequirement(
                state_code="CA",
                state_name="California",
                has_state_income_tax=True,
                state_tax_rate=Decimal("0.093"),  # Starting rate
                is_progressive=True,
                filing_deadline=date(date.today().year, 4, 15),
                requires_quarterly_estimates=True
            ),
            "TX": StateFilingRequirement(
                state_code="TX",
                state_name="Texas",
                has_state_income_tax=False,
            ),
            "FL": StateFilingRequirement(
                state_code="FL",
                state_name="Florida",
                has_state_income_tax=False,
            ),
            "NY": StateFilingRequirement(
                state_code="NY",
                state_name="New York",
                has_state_income_tax=True,
                state_tax_rate=Decimal("0.04"),  # Starting rate
                is_progressive=True,
                filing_deadline=date(date.today().year, 4, 15),
                requires_quarterly_estimates=True
            ),
        }

        return state_rules.get(
            state_code,
            StateFilingRequirement(
                state_code=state_code,
                state_name=state_code,
                has_state_income_tax=False
            )
        )

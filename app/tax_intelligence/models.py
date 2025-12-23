# app/tax_intelligence/models.py

from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# QUARTERLY TAX ESTIMATES
# ============================================================================

class TaxQuarter(str, Enum):
    Q1 = "Q1"  # Jan 1 - Mar 31, due Apr 15
    Q2 = "Q2"  # Apr 1 - May 31, due Jun 15
    Q3 = "Q3"  # Jun 1 - Aug 31, due Sep 15
    Q4 = "Q4"  # Sep 1 - Dec 31, due Jan 15 (next year)


class QuarterlyTaxPayment(BaseModel):
    """Quarterly estimated tax payment"""
    quarter: TaxQuarter
    tax_year: int
    due_date: date

    # Income components
    gross_income: Decimal = Decimal("0.00")
    deductions: Decimal = Decimal("0.00")
    taxable_income: Decimal = Decimal("0.00")

    # Tax calculations
    federal_income_tax: Decimal = Decimal("0.00")
    self_employment_tax: Decimal = Decimal("0.00")
    state_tax: Decimal = Decimal("0.00")
    total_tax_due: Decimal = Decimal("0.00")

    # Payment tracking
    amount_paid: Decimal = Decimal("0.00")
    payment_date: Optional[date] = None
    is_paid: bool = False

    # Penalties
    underpayment_penalty: Decimal = Decimal("0.00")
    late_payment_penalty: Decimal = Decimal("0.00")


class TaxEstimate(BaseModel):
    """Annual tax estimate with quarterly breakdown"""
    tax_year: int
    organization_id: str
    business_type: str  # "Schedule C", "S-Corp", "Partnership", etc.
    filing_status: str  # "Single", "Married Filing Jointly", etc.

    # Annual totals
    total_gross_income: Decimal = Decimal("0.00")
    total_deductions: Decimal = Decimal("0.00")
    total_taxable_income: Decimal = Decimal("0.00")

    total_federal_tax: Decimal = Decimal("0.00")
    total_self_employment_tax: Decimal = Decimal("0.00")
    total_state_tax: Decimal = Decimal("0.00")
    total_tax_liability: Decimal = Decimal("0.00")

    total_paid: Decimal = Decimal("0.00")
    balance_due: Decimal = Decimal("0.00")

    # Quarterly breakdown
    quarterly_payments: List[QuarterlyTaxPayment] = []

    # Effective rates
    effective_tax_rate: Decimal = Decimal("0.00")  # percentage
    marginal_tax_rate: Decimal = Decimal("0.00")  # percentage


# ============================================================================
# DEDUCTION OPTIMIZATION
# ============================================================================

class DeductionCategory(BaseModel):
    """Category of tax deductions"""
    category_name: str
    schedule_c_line: Optional[str] = None  # "Line 8", "Line 9", etc.

    total_expenses: Decimal = Decimal("0.00")
    deductible_amount: Decimal = Decimal("0.00")
    deduction_rate: Decimal = Decimal("1.00")  # 1.00 = 100% deductible

    # Recommendations
    optimization_potential: Decimal = Decimal("0.00")
    recommendations: List[str] = []
    warnings: List[str] = []

    # Tax savings
    tax_savings: Decimal = Decimal("0.00")


class DeductionOptimization(BaseModel):
    """Deduction optimization report"""
    tax_year: int
    organization_id: str
    as_of_date: date

    # Categories
    categories: List[DeductionCategory] = []

    # Totals
    total_expenses: Decimal = Decimal("0.00")
    total_deductions: Decimal = Decimal("0.00")
    potential_additional_deductions: Decimal = Decimal("0.00")

    # Tax impact
    current_tax_liability: Decimal = Decimal("0.00")
    optimized_tax_liability: Decimal = Decimal("0.00")
    potential_tax_savings: Decimal = Decimal("0.00")

    # Top recommendations
    top_recommendations: List[str] = []

    # Missing deductions
    commonly_missed: List[str] = []


# ============================================================================
# TAX DEADLINES & CALENDAR
# ============================================================================

class DeadlineType(str, Enum):
    QUARTERLY_ESTIMATE = "quarterly_estimate"
    ANNUAL_FILING = "annual_filing"
    EXTENSION = "extension"
    PAYROLL = "payroll"
    SALES_TAX = "sales_tax"
    FORM_1099 = "form_1099"
    OTHER = "other"


class TaxDeadline(BaseModel):
    """Individual tax deadline"""
    deadline_id: str
    deadline_type: DeadlineType
    description: str
    due_date: date

    # Context
    tax_year: Optional[int] = None
    quarter: Optional[TaxQuarter] = None
    form_number: Optional[str] = None  # "1040", "941", "1099-MISC", etc.

    # Status
    is_completed: bool = False
    completed_date: Optional[date] = None

    # Penalties
    penalty_per_day: Optional[Decimal] = None
    max_penalty: Optional[Decimal] = None

    # Reminders
    reminder_days: int = 30  # Remind 30 days before due date


class TaxCalendar(BaseModel):
    """Tax calendar for a business"""
    tax_year: int
    organization_id: str
    business_type: str
    state: Optional[str] = None

    deadlines: List[TaxDeadline] = []

    # Upcoming deadlines (next 90 days)
    upcoming_count: int = 0
    overdue_count: int = 0


# ============================================================================
# STATE-SPECIFIC TAX RULES
# ============================================================================

class StateFilingRequirement(BaseModel):
    """State-specific filing requirements"""
    state_code: str  # "CA", "TX", "NY", etc.
    state_name: str

    # State income tax
    has_state_income_tax: bool
    state_tax_rate: Optional[Decimal] = None  # Flat rate or starting rate
    is_progressive: bool = False

    # Filing requirements
    minimum_income_threshold: Decimal = Decimal("0.00")
    filing_deadline: Optional[date] = None
    extension_deadline: Optional[date] = None

    # Quarterly estimates
    requires_quarterly_estimates: bool = False
    quarterly_due_dates: List[date] = []

    # Special rules
    special_deductions: List[str] = []
    special_credits: List[str] = []
    notes: str = ""


# ============================================================================
# TAX PROJECTIONS
# ============================================================================

class TaxProjection(BaseModel):
    """Tax projection based on current year-to-date performance"""
    organization_id: str
    projection_date: date
    tax_year: int

    # YTD actuals
    ytd_income: Decimal = Decimal("0.00")
    ytd_expenses: Decimal = Decimal("0.00")
    ytd_net_income: Decimal = Decimal("0.00")

    # Projected year-end
    projected_annual_income: Decimal = Decimal("0.00")
    projected_annual_expenses: Decimal = Decimal("0.00")
    projected_annual_net_income: Decimal = Decimal("0.00")

    # Tax projections
    projected_federal_tax: Decimal = Decimal("0.00")
    projected_self_employment_tax: Decimal = Decimal("0.00")
    projected_state_tax: Decimal = Decimal("0.00")
    projected_total_tax: Decimal = Decimal("0.00")

    # Cash flow planning
    taxes_paid_ytd: Decimal = Decimal("0.00")
    remaining_tax_liability: Decimal = Decimal("0.00")

    # Recommendations
    recommended_q4_payment: Decimal = Decimal("0.00")
    cash_reserve_needed: Decimal = Decimal("0.00")

    # Comparison
    vs_last_year_income_change: Optional[Decimal] = None
    vs_last_year_tax_change: Optional[Decimal] = None


# ============================================================================
# TAX BRACKETS (for calculations)
# ============================================================================

class TaxBracket(BaseModel):
    """Federal tax bracket"""
    filing_status: str
    min_income: Decimal
    max_income: Optional[Decimal] = None  # None for top bracket
    rate: Decimal  # 0.10 for 10%, 0.12 for 12%, etc.


# 2024 Federal Tax Brackets (Schedule C filers - Single)
FEDERAL_TAX_BRACKETS_2024_SINGLE = [
    TaxBracket(filing_status="Single", min_income=Decimal("0"), max_income=Decimal("11600"), rate=Decimal("0.10")),
    TaxBracket(filing_status="Single", min_income=Decimal("11600"), max_income=Decimal("47150"), rate=Decimal("0.12")),
    TaxBracket(filing_status="Single", min_income=Decimal("47150"), max_income=Decimal("100525"), rate=Decimal("0.22")),
    TaxBracket(filing_status="Single", min_income=Decimal("100525"), max_income=Decimal("191950"), rate=Decimal("0.24")),
    TaxBracket(filing_status="Single", min_income=Decimal("191950"), max_income=Decimal("243725"), rate=Decimal("0.32")),
    TaxBracket(filing_status="Single", min_income=Decimal("243725"), max_income=Decimal("609350"), rate=Decimal("0.35")),
    TaxBracket(filing_status="Single", min_income=Decimal("609350"), max_income=None, rate=Decimal("0.37")),
]

# 2024 Federal Tax Brackets (Married Filing Jointly)
FEDERAL_TAX_BRACKETS_2024_MARRIED = [
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("0"), max_income=Decimal("23200"), rate=Decimal("0.10")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("23200"), max_income=Decimal("94300"), rate=Decimal("0.12")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("94300"), max_income=Decimal("201050"), rate=Decimal("0.22")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("201050"), max_income=Decimal("383900"), rate=Decimal("0.24")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("383900"), max_income=Decimal("487450"), rate=Decimal("0.32")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("487450"), max_income=Decimal("731200"), rate=Decimal("0.35")),
    TaxBracket(filing_status="Married Filing Jointly", min_income=Decimal("731200"), max_income=None, rate=Decimal("0.37")),
]

# Self-Employment Tax Rate (2024)
SELF_EMPLOYMENT_TAX_RATE = Decimal("0.1530")  # 15.30% (Social Security 12.4% + Medicare 2.9%)
SELF_EMPLOYMENT_DEDUCTION_RATE = Decimal("0.9235")  # Deduct employer portion (7.65%)
SOCIAL_SECURITY_WAGE_BASE = Decimal("168600")  # 2024 limit

# Standard Deductions (2024)
STANDARD_DEDUCTION_2024 = {
    "Single": Decimal("14600"),
    "Married Filing Jointly": Decimal("29200"),
    "Married Filing Separately": Decimal("14600"),
    "Head of Household": Decimal("21900"),
}

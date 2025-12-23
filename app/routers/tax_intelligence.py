# app/routers/tax_intelligence.py

from __future__ import annotations
from datetime import date
from typing import Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query

from app.tax_intelligence.models import (
    TaxEstimate,
    DeductionOptimization,
    TaxCalendar,
    TaxProjection,
    StateFilingRequirement,
)
from app.tax_intelligence.engine import TaxIntelligenceEngine
from app.routers.auth import get_current_organization_id

router = APIRouter(prefix="/api/tax-intelligence", tags=["Tax Intelligence"])

# Global engine instance (will be set at startup)
_tax_engine: Optional[TaxIntelligenceEngine] = None


def set_tax_engine(engine: TaxIntelligenceEngine):
    """Set the tax engine (called at startup)"""
    global _tax_engine
    _tax_engine = engine


def get_tax_engine() -> TaxIntelligenceEngine:
    """Get the tax engine"""
    if _tax_engine is None:
        raise HTTPException(status_code=500, detail="Tax engine not initialized")
    return _tax_engine


# ============================================================================
# QUARTERLY TAX ESTIMATES
# ============================================================================

@router.get("/estimates/{tax_year}", response_model=TaxEstimate)
async def get_quarterly_estimates(
    tax_year: int,
    filing_status: str = Query("Single", description="Single, Married Filing Jointly, etc."),
    business_type: str = Query("Schedule C", description="Business type"),
    state_code: Optional[str] = Query(None, description="Two-letter state code (e.g., CA, NY)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get quarterly estimated tax payments for the year.

    Calculates:
    - Federal income tax
    - Self-employment tax
    - State tax (if applicable)
    - Quarterly payment schedule
    """
    engine = get_tax_engine()
    return engine.calculate_quarterly_estimates(
        organization_id,
        tax_year,
        filing_status,
        business_type,
        state_code
    )


# ============================================================================
# DEDUCTION OPTIMIZATION
# ============================================================================

@router.get("/deductions/{tax_year}", response_model=DeductionOptimization)
async def optimize_deductions(
    tax_year: int,
    marginal_tax_rate: Optional[Decimal] = Query(None, description="Marginal tax rate (0.24 for 24%, etc.)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get deduction optimization recommendations.

    Analyzes expenses and identifies:
    - Underutilized deductions
    - Commonly missed deductions
    - Tax-saving opportunities
    """
    engine = get_tax_engine()
    return engine.optimize_deductions(
        organization_id,
        tax_year,
        marginal_tax_rate
    )


# ============================================================================
# TAX CALENDAR
# ============================================================================

@router.get("/calendar/{tax_year}", response_model=TaxCalendar)
async def get_tax_calendar(
    tax_year: int,
    business_type: str = Query("Schedule C", description="Business type"),
    state_code: Optional[str] = Query(None, description="Two-letter state code"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get tax calendar with all filing deadlines.

    Includes:
    - Quarterly estimated payments
    - Annual filing deadlines
    - Form 1099 deadlines
    - State deadlines
    """
    engine = get_tax_engine()
    return engine.get_tax_calendar(
        organization_id,
        tax_year,
        business_type,
        state_code
    )


# ============================================================================
# TAX PROJECTIONS
# ============================================================================

@router.get("/projection/{tax_year}", response_model=TaxProjection)
async def get_tax_projection(
    tax_year: int,
    filing_status: str = Query("Single", description="Filing status"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Project year-end tax liability based on YTD performance.

    Returns:
    - YTD actuals
    - Projected year-end income and expenses
    - Projected total tax liability
    - Recommended Q4 payment
    - Cash reserve needed
    """
    engine = get_tax_engine()
    return engine.project_year_end_taxes(
        organization_id,
        tax_year,
        filing_status
    )


# ============================================================================
# TAX PLANNING SUMMARY
# ============================================================================

@router.get("/summary/{tax_year}")
async def get_tax_summary(
    tax_year: int,
    filing_status: str = Query("Single"),
    state_code: Optional[str] = Query(None),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get comprehensive tax planning summary.

    Combines:
    - Quarterly estimates
    - Deduction optimization
    - Tax calendar (upcoming deadlines)
    - Year-end projection
    """
    engine = get_tax_engine()

    # Get all components
    estimates = engine.calculate_quarterly_estimates(
        organization_id,
        tax_year,
        filing_status,
        "Schedule C",
        state_code
    )

    deductions = engine.optimize_deductions(
        organization_id,
        tax_year
    )

    calendar = engine.get_tax_calendar(
        organization_id,
        tax_year,
        "Schedule C",
        state_code
    )

    projection = engine.project_year_end_taxes(
        organization_id,
        tax_year,
        filing_status
    )

    return {
        "tax_year": tax_year,
        "estimates": {
            "total_tax_liability": estimates.total_tax_liability,
            "effective_tax_rate": estimates.effective_tax_rate,
            "marginal_tax_rate": estimates.marginal_tax_rate,
            "next_payment": next(
                (q for q in estimates.quarterly_payments if not q.is_paid),
                None
            ),
        },
        "deductions": {
            "total_deductions": deductions.total_deductions,
            "potential_tax_savings": deductions.potential_tax_savings,
            "top_recommendations": deductions.top_recommendations[:3],
            "commonly_missed": deductions.commonly_missed[:5],
        },
        "calendar": {
            "upcoming_count": calendar.upcoming_count,
            "overdue_count": calendar.overdue_count,
            "next_deadline": min(
                (d for d in calendar.deadlines if not d.is_completed and d.due_date >= date.today()),
                key=lambda x: x.due_date,
                default=None
            ),
        },
        "projection": {
            "projected_annual_income": projection.projected_annual_income,
            "projected_total_tax": projection.projected_total_tax,
            "remaining_tax_liability": projection.remaining_tax_liability,
            "recommended_q4_payment": projection.recommended_q4_payment,
            "cash_reserve_needed": projection.cash_reserve_needed,
        },
    }

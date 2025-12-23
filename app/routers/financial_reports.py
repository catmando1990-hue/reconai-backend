# app/routers/financial_reports.py

from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from app.financial_reports.models import (
    ProfitLossReport,
    BalanceSheetReport,
    CashFlowReport,
    FinancialRatios,
    TrendAnalysis,
)
from app.financial_reports.engine import FinancialReportsEngine
from app.routers.auth import get_current_organization_id

router = APIRouter(prefix="/api/financial-reports", tags=["Financial Reports"])

# Global engine instance (will be set at startup)
_reports_engine: Optional[FinancialReportsEngine] = None


def set_reports_engine(engine: FinancialReportsEngine):
    """Set the reports engine (called at startup)"""
    global _reports_engine
    _reports_engine = engine


def get_reports_engine() -> FinancialReportsEngine:
    """Get the reports engine"""
    if _reports_engine is None:
        raise HTTPException(status_code=500, detail="Reports engine not initialized")
    return _reports_engine


# ============================================================================
# PROFIT & LOSS ENDPOINTS
# ============================================================================

@router.get("/profit-loss", response_model=ProfitLossReport)
async def get_profit_loss(
    start_date: date = Query(..., description="Period start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Period end date (YYYY-MM-DD)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get Profit & Loss Statement (Income Statement).

    Shows revenue, expenses, and net income for the specified period.
    """
    engine = get_reports_engine()
    return engine.generate_profit_loss(organization_id, start_date, end_date)


# ============================================================================
# BALANCE SHEET ENDPOINTS
# ============================================================================

@router.get("/balance-sheet", response_model=BalanceSheetReport)
async def get_balance_sheet(
    as_of_date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get Balance Sheet.

    Shows assets, liabilities, and equity as of the specified date.
    """
    engine = get_reports_engine()
    return engine.generate_balance_sheet(organization_id, as_of_date)


# ============================================================================
# CASH FLOW ENDPOINTS
# ============================================================================

@router.get("/cash-flow", response_model=CashFlowReport)
async def get_cash_flow(
    start_date: date = Query(..., description="Period start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Period end date (YYYY-MM-DD)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get Cash Flow Statement.

    Shows operating, investing, and financing cash flows for the specified period.
    """
    engine = get_reports_engine()
    return engine.generate_cash_flow(organization_id, start_date, end_date)


# ============================================================================
# FINANCIAL RATIOS ENDPOINTS
# ============================================================================

@router.get("/ratios", response_model=FinancialRatios)
async def get_financial_ratios(
    as_of_date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    period_start: Optional[date] = Query(None, description="Period start for P&L-based ratios (defaults to YTD)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get Financial Ratios.

    Calculates liquidity, profitability, leverage, and efficiency ratios.
    """
    engine = get_reports_engine()
    return engine.calculate_financial_ratios(organization_id, as_of_date, period_start)


# ============================================================================
# TREND ANALYSIS ENDPOINTS
# ============================================================================

@router.get("/trends/{metric_name}", response_model=TrendAnalysis)
async def get_trend_analysis(
    metric_name: str,
    start_date: date = Query(..., description="Period start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Period end date (YYYY-MM-DD)"),
    period_type: str = Query("monthly", description="Period type: monthly, quarterly, yearly"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get Trend Analysis for a specific metric.

    Supported metrics:
    - Revenue
    - Net Income
    - Gross Profit
    - Operating Expenses
    - Operating Income
    - Cash Balance
    """
    if period_type not in ["monthly", "quarterly", "yearly"]:
        raise HTTPException(
            status_code=400,
            detail="period_type must be 'monthly', 'quarterly', or 'yearly'"
        )

    engine = get_reports_engine()
    return engine.generate_trend_analysis(
        organization_id,
        metric_name,
        period_type,
        start_date,
        end_date
    )


# ============================================================================
# DASHBOARD SUMMARY ENDPOINT
# ============================================================================

@router.get("/dashboard-summary")
async def get_dashboard_summary(
    as_of_date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    organization_id: str = Depends(get_current_organization_id)
):
    """
    Get comprehensive dashboard summary with all key financial metrics.

    Returns:
    - Current month P&L
    - YTD P&L
    - Balance Sheet
    - Key ratios
    - Revenue trend (last 12 months)
    """
    engine = get_reports_engine()

    from datetime import timedelta
    from dateutil.relativedelta import relativedelta

    # Current month P&L
    month_start = date(as_of_date.year, as_of_date.month, 1)
    current_month_pl = engine.generate_profit_loss(organization_id, month_start, as_of_date)

    # YTD P&L
    ytd_start = date(as_of_date.year, 1, 1)
    ytd_pl = engine.generate_profit_loss(organization_id, ytd_start, as_of_date)

    # Balance Sheet
    balance_sheet = engine.generate_balance_sheet(organization_id, as_of_date)

    # Financial Ratios
    ratios = engine.calculate_financial_ratios(organization_id, as_of_date, ytd_start)

    # Revenue trend (last 12 months)
    trend_start = as_of_date - relativedelta(months=11)
    trend_start = date(trend_start.year, trend_start.month, 1)  # First of the month
    revenue_trend = engine.generate_trend_analysis(
        organization_id,
        "Revenue",
        "monthly",
        trend_start,
        as_of_date
    )

    return {
        "as_of_date": as_of_date,
        "current_month": {
            "revenue": current_month_pl.total_revenue,
            "net_income": current_month_pl.net_income,
            "operating_margin": current_month_pl.operating_margin,
        },
        "year_to_date": {
            "revenue": ytd_pl.total_revenue,
            "net_income": ytd_pl.net_income,
            "operating_margin": ytd_pl.operating_margin,
        },
        "balance_sheet": {
            "total_assets": balance_sheet.total_assets,
            "total_liabilities": balance_sheet.total_liabilities,
            "total_equity": balance_sheet.total_equity,
            "working_capital": balance_sheet.current_assets - balance_sheet.current_liabilities,
            "is_balanced": balance_sheet.is_balanced,
        },
        "ratios": {
            "current_ratio": ratios.current_ratio,
            "quick_ratio": ratios.quick_ratio,
            "net_profit_margin": ratios.net_profit_margin,
            "return_on_assets": ratios.return_on_assets,
            "return_on_equity": ratios.return_on_equity,
            "debt_to_equity": ratios.debt_to_equity,
        },
        "revenue_trend": revenue_trend.data_points,
    }

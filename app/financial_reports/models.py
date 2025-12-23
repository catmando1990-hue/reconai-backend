# app/financial_reports/models.py

from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional
from pydantic import BaseModel, Field


# ============================================================================
# PROFIT & LOSS (INCOME STATEMENT)
# ============================================================================

class PLCategory(BaseModel):
    """P&L category line item"""
    category_name: str
    amount: Decimal
    percentage_of_revenue: Optional[Decimal] = None

class ProfitLossReport(BaseModel):
    """Profit & Loss Statement (Income Statement)"""
    start_date: date
    end_date: date
    organization_id: str

    # Revenue
    total_revenue: Decimal = Decimal("0.00")
    revenue_breakdown: List[PLCategory] = []

    # Cost of Goods Sold
    cost_of_goods_sold: Decimal = Decimal("0.00")
    gross_profit: Decimal = Decimal("0.00")
    gross_profit_margin: Decimal = Decimal("0.00")  # percentage

    # Operating Expenses
    total_operating_expenses: Decimal = Decimal("0.00")
    operating_expenses_breakdown: List[PLCategory] = []

    # Operating Income
    operating_income: Decimal = Decimal("0.00")
    operating_margin: Decimal = Decimal("0.00")  # percentage

    # Other Income/Expense
    other_income: Decimal = Decimal("0.00")
    other_expenses: Decimal = Decimal("0.00")
    interest_income: Decimal = Decimal("0.00")
    interest_expense: Decimal = Decimal("0.00")

    # Net Income
    net_income_before_tax: Decimal = Decimal("0.00")
    net_income: Decimal = Decimal("0.00")
    net_profit_margin: Decimal = Decimal("0.00")  # percentage


# ============================================================================
# BALANCE SHEET
# ============================================================================

class BSCategory(BaseModel):
    """Balance sheet category"""
    category_name: str
    amount: Decimal

class BalanceSheetReport(BaseModel):
    """Balance Sheet"""
    as_of_date: date
    organization_id: str

    # Assets
    current_assets: Decimal = Decimal("0.00")
    current_assets_breakdown: List[BSCategory] = []

    fixed_assets: Decimal = Decimal("0.00")
    fixed_assets_breakdown: List[BSCategory] = []

    total_assets: Decimal = Decimal("0.00")

    # Liabilities
    current_liabilities: Decimal = Decimal("0.00")
    current_liabilities_breakdown: List[BSCategory] = []

    long_term_liabilities: Decimal = Decimal("0.00")
    long_term_liabilities_breakdown: List[BSCategory] = []

    total_liabilities: Decimal = Decimal("0.00")

    # Equity
    owners_equity: Decimal = Decimal("0.00")
    retained_earnings: Decimal = Decimal("0.00")
    total_equity: Decimal = Decimal("0.00")

    # Accounting Equation Check
    is_balanced: bool = True
    balance_difference: Decimal = Decimal("0.00")


# ============================================================================
# CASH FLOW STATEMENT
# ============================================================================

class CFCategory(BaseModel):
    """Cash flow category"""
    category_name: str
    amount: Decimal

class CashFlowReport(BaseModel):
    """Cash Flow Statement"""
    start_date: date
    end_date: date
    organization_id: str

    # Operating Activities
    net_income: Decimal = Decimal("0.00")
    operating_adjustments: List[CFCategory] = []
    cash_from_operations: Decimal = Decimal("0.00")

    # Investing Activities
    investing_activities: List[CFCategory] = []
    cash_from_investing: Decimal = Decimal("0.00")

    # Financing Activities
    financing_activities: List[CFCategory] = []
    cash_from_financing: Decimal = Decimal("0.00")

    # Net Change
    net_cash_change: Decimal = Decimal("0.00")
    beginning_cash: Decimal = Decimal("0.00")
    ending_cash: Decimal = Decimal("0.00")


# ============================================================================
# FINANCIAL RATIOS
# ============================================================================

class FinancialRatios(BaseModel):
    """Key financial ratios"""
    as_of_date: date
    organization_id: str

    # Liquidity Ratios
    current_ratio: Optional[Decimal] = None  # Current Assets / Current Liabilities
    quick_ratio: Optional[Decimal] = None  # (Current Assets - Inventory) / Current Liabilities
    cash_ratio: Optional[Decimal] = None  # Cash / Current Liabilities

    # Profitability Ratios
    gross_margin: Optional[Decimal] = None  # (Revenue - COGS) / Revenue
    operating_margin: Optional[Decimal] = None  # Operating Income / Revenue
    net_profit_margin: Optional[Decimal] = None  # Net Income / Revenue
    return_on_assets: Optional[Decimal] = None  # Net Income / Total Assets
    return_on_equity: Optional[Decimal] = None  # Net Income / Total Equity

    # Leverage Ratios
    debt_to_equity: Optional[Decimal] = None  # Total Liabilities / Total Equity
    debt_ratio: Optional[Decimal] = None  # Total Liabilities / Total Assets
    equity_ratio: Optional[Decimal] = None  # Total Equity / Total Assets

    # Efficiency Ratios
    asset_turnover: Optional[Decimal] = None  # Revenue / Total Assets

    # Working Capital
    working_capital: Optional[Decimal] = None  # Current Assets - Current Liabilities


# ============================================================================
# TREND ANALYSIS
# ============================================================================

class TrendDataPoint(BaseModel):
    """Single data point in trend"""
    period: str  # "2024-01", "2024-Q1", etc.
    value: Decimal
    change_from_previous: Optional[Decimal] = None  # Dollar amount
    percent_change: Optional[Decimal] = None  # Percentage

class TrendAnalysis(BaseModel):
    """Trend analysis for key metrics"""
    organization_id: str
    metric_name: str  # "Revenue", "Net Income", etc.
    period_type: str  # "monthly", "quarterly", "yearly"
    data_points: List[TrendDataPoint] = []

    # Summary statistics
    average: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    min_value: Decimal = Decimal("0.00")
    max_value: Decimal = Decimal("0.00")
    overall_change: Decimal = Decimal("0.00")
    overall_percent_change: Decimal = Decimal("0.00")

# app/financial_reports/engine.py

from __future__ import annotations
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from app.financial_reports.models import (
    ProfitLossReport,
    PLCategory,
    BalanceSheetReport,
    BSCategory,
    CashFlowReport,
    CFCategory,
    FinancialRatios,
    TrendAnalysis,
    TrendDataPoint,
)
from app.bookkeeping.engine import BookkeeperEngine
from app.bookkeeping.models import AccountType


class FinancialReportsEngine:
    """
    Generate financial reports from bookkeeping data.

    This engine integrates with the BookkeeperEngine to:
    - Generate Profit & Loss (Income Statement)
    - Generate Balance Sheet
    - Generate Cash Flow Statement
    - Calculate Financial Ratios
    - Provide Trend Analysis
    """

    def __init__(self, bookkeeper_engine: BookkeeperEngine):
        self.bookkeeper = bookkeeper_engine

    # ========================================================================
    # PROFIT & LOSS (INCOME STATEMENT)
    # ========================================================================

    def generate_profit_loss(
        self,
        organization_id: str,
        start_date: date,
        end_date: date
    ) -> ProfitLossReport:
        """
        Generate Profit & Loss Statement (Income Statement).

        P&L shows:
        - Total Revenue
        - Cost of Goods Sold (COGS)
        - Gross Profit
        - Operating Expenses
        - Operating Income
        - Other Income/Expenses
        - Net Income
        """
        report = ProfitLossReport(
            start_date=start_date,
            end_date=end_date,
            organization_id=organization_id
        )

        # Get all accounts
        accounts = self.bookkeeper.get_chart_of_accounts(organization_id)

        # Get account balances for the period
        revenue_accounts = [a for a in accounts if a.account_type == AccountType.REVENUE]
        expense_accounts = [a for a in accounts if a.account_type == AccountType.EXPENSE]

        # Calculate revenue
        for account in revenue_accounts:
            balance = self._get_period_balance(
                account.account_id,
                start_date,
                end_date,
                organization_id
            )

            if balance > 0:
                # Revenue has credit normal balance
                report.total_revenue += balance

                # Categorize revenue
                if account.account_subtype:
                    report.revenue_breakdown.append(
                        PLCategory(
                            category_name=account.account_name,
                            amount=balance
                        )
                    )

        # Calculate expenses by category
        cogs_total = Decimal("0.00")
        operating_expenses = Decimal("0.00")
        other_expenses = Decimal("0.00")
        interest_expense = Decimal("0.00")

        for account in expense_accounts:
            balance = self._get_period_balance(
                account.account_id,
                start_date,
                end_date,
                organization_id
            )

            if balance > 0:
                # Expenses have debit normal balance

                # Categorize expense
                subtype = (account.account_subtype or "").lower()

                if "cogs" in subtype or "cost of goods" in subtype:
                    cogs_total += balance
                elif "interest" in subtype:
                    interest_expense += balance
                    other_expenses += balance
                elif "other" in subtype:
                    other_expenses += balance
                else:
                    operating_expenses += balance
                    report.operating_expenses_breakdown.append(
                        PLCategory(
                            category_name=account.account_name,
                            amount=balance
                        )
                    )

        # Set expense totals
        report.cost_of_goods_sold = cogs_total
        report.total_operating_expenses = operating_expenses
        report.other_expenses = other_expenses
        report.interest_expense = interest_expense

        # Calculate derived metrics
        report.gross_profit = report.total_revenue - report.cost_of_goods_sold

        if report.total_revenue > 0:
            report.gross_profit_margin = (report.gross_profit / report.total_revenue) * 100

        report.operating_income = report.gross_profit - report.total_operating_expenses

        if report.total_revenue > 0:
            report.operating_margin = (report.operating_income / report.total_revenue) * 100

        report.net_income_before_tax = (
            report.operating_income +
            report.other_income -
            report.other_expenses
        )

        # For now, assume no tax withholding (could add tax calculation later)
        report.net_income = report.net_income_before_tax

        if report.total_revenue > 0:
            report.net_profit_margin = (report.net_income / report.total_revenue) * 100

        # Calculate percentage of revenue for each category
        for category in report.revenue_breakdown:
            if report.total_revenue > 0:
                category.percentage_of_revenue = (category.amount / report.total_revenue) * 100

        for category in report.operating_expenses_breakdown:
            if report.total_revenue > 0:
                category.percentage_of_revenue = (category.amount / report.total_revenue) * 100

        return report

    # ========================================================================
    # BALANCE SHEET
    # ========================================================================

    def generate_balance_sheet(
        self,
        organization_id: str,
        as_of_date: date
    ) -> BalanceSheetReport:
        """
        Generate Balance Sheet.

        Balance Sheet shows:
        - Assets (Current + Fixed)
        - Liabilities (Current + Long-term)
        - Equity (Owner's Equity + Retained Earnings)

        Must satisfy: Assets = Liabilities + Equity
        """
        report = BalanceSheetReport(
            as_of_date=as_of_date,
            organization_id=organization_id
        )

        # Get all accounts
        accounts = self.bookkeeper.get_chart_of_accounts(organization_id)

        # Categorize accounts
        asset_accounts = [a for a in accounts if a.account_type == AccountType.ASSET]
        liability_accounts = [a for a in accounts if a.account_type == AccountType.LIABILITY]
        equity_accounts = [a for a in accounts if a.account_type == AccountType.EQUITY]

        # Calculate assets
        for account in asset_accounts:
            balance = self._get_balance_as_of(account.account_id, as_of_date, organization_id)

            if balance != 0:
                subtype = (account.account_subtype or "").lower()

                category = BSCategory(
                    category_name=account.account_name,
                    amount=balance
                )

                # Categorize as current or fixed
                if any(term in subtype for term in ["current", "cash", "receivable", "inventory", "prepaid"]):
                    report.current_assets += balance
                    report.current_assets_breakdown.append(category)
                else:
                    report.fixed_assets += balance
                    report.fixed_assets_breakdown.append(category)

        report.total_assets = report.current_assets + report.fixed_assets

        # Calculate liabilities
        for account in liability_accounts:
            balance = self._get_balance_as_of(account.account_id, as_of_date, organization_id)

            if balance != 0:
                subtype = (account.account_subtype or "").lower()

                category = BSCategory(
                    category_name=account.account_name,
                    amount=balance
                )

                # Categorize as current or long-term
                if any(term in subtype for term in ["current", "payable", "accrued", "short-term"]):
                    report.current_liabilities += balance
                    report.current_liabilities_breakdown.append(category)
                else:
                    report.long_term_liabilities += balance
                    report.long_term_liabilities_breakdown.append(category)

        report.total_liabilities = report.current_liabilities + report.long_term_liabilities

        # Calculate equity
        for account in equity_accounts:
            balance = self._get_balance_as_of(account.account_id, as_of_date, organization_id)

            if balance != 0:
                subtype = (account.account_subtype or "").lower()

                if "retained" in subtype or "earnings" in subtype:
                    report.retained_earnings += balance
                else:
                    report.owners_equity += balance

        report.total_equity = report.owners_equity + report.retained_earnings

        # Accounting equation check: Assets = Liabilities + Equity
        report.balance_difference = report.total_assets - (report.total_liabilities + report.total_equity)
        report.is_balanced = abs(report.balance_difference) < Decimal("0.01")  # Allow 1 cent rounding

        return report

    # ========================================================================
    # CASH FLOW STATEMENT
    # ========================================================================

    def generate_cash_flow(
        self,
        organization_id: str,
        start_date: date,
        end_date: date
    ) -> CashFlowReport:
        """
        Generate Cash Flow Statement.

        Cash Flow shows:
        - Operating Activities (Net Income + Adjustments)
        - Investing Activities (CapEx, Asset purchases/sales)
        - Financing Activities (Debt, Equity)
        - Net Change in Cash
        """
        report = CashFlowReport(
            start_date=start_date,
            end_date=end_date,
            organization_id=organization_id
        )

        # Get Net Income from P&L
        pl_report = self.generate_profit_loss(organization_id, start_date, end_date)
        report.net_income = pl_report.net_income

        # Get cash account to calculate net change
        accounts = self.bookkeeper.get_chart_of_accounts(organization_id)
        cash_accounts = [a for a in accounts if "cash" in a.account_name.lower()]

        if cash_accounts:
            cash_account = cash_accounts[0]

            # Beginning cash
            report.beginning_cash = self._get_balance_as_of(
                cash_account.account_id,
                start_date - timedelta(days=1),
                organization_id
            )

            # Ending cash
            report.ending_cash = self._get_balance_as_of(
                cash_account.account_id,
                end_date,
                organization_id
            )

        # For now, simplified cash flow calculation
        # In a full implementation, we'd analyze all balance sheet changes

        # Operating Activities Adjustments
        # (Add back non-cash expenses like depreciation, adjust for A/R and A/P changes)
        # This is simplified - a full implementation would track all these

        report.cash_from_operations = report.net_income  # Simplified

        # Investing Activities
        # (Track capital expenditures, asset purchases/sales)
        # Simplified for now
        report.cash_from_investing = Decimal("0.00")

        # Financing Activities
        # (Track debt, equity transactions)
        # Simplified for now
        report.cash_from_financing = Decimal("0.00")

        # Net Change
        report.net_cash_change = (
            report.cash_from_operations +
            report.cash_from_investing +
            report.cash_from_financing
        )

        # Verify: Beginning + Net Change = Ending
        calculated_ending = report.beginning_cash + report.net_cash_change
        # Note: This may not match perfectly in simplified version

        return report

    # ========================================================================
    # FINANCIAL RATIOS
    # ========================================================================

    def calculate_financial_ratios(
        self,
        organization_id: str,
        as_of_date: date,
        period_start: Optional[date] = None
    ) -> FinancialRatios:
        """
        Calculate key financial ratios.

        Ratios include:
        - Liquidity: Current Ratio, Quick Ratio, Cash Ratio
        - Profitability: Margins, ROA, ROE
        - Leverage: Debt-to-Equity, Debt Ratio
        - Efficiency: Asset Turnover
        """
        ratios = FinancialRatios(
            as_of_date=as_of_date,
            organization_id=organization_id
        )

        # Get Balance Sheet
        bs = self.generate_balance_sheet(organization_id, as_of_date)

        # Get P&L for the year to date
        if period_start is None:
            period_start = date(as_of_date.year, 1, 1)

        pl = self.generate_profit_loss(organization_id, period_start, as_of_date)

        # Liquidity Ratios
        if bs.current_liabilities > 0:
            ratios.current_ratio = bs.current_assets / bs.current_liabilities

            # Quick Ratio = (Current Assets - Inventory) / Current Liabilities
            # Simplified: assume no inventory for service businesses
            ratios.quick_ratio = bs.current_assets / bs.current_liabilities

            # Cash Ratio - need to find cash account
            accounts = self.bookkeeper.get_chart_of_accounts(organization_id)
            cash_accounts = [a for a in accounts if "cash" in a.account_name.lower()]
            if cash_accounts:
                cash_balance = self._get_balance_as_of(cash_accounts[0].account_id, as_of_date, organization_id)
                ratios.cash_ratio = cash_balance / bs.current_liabilities

        # Profitability Ratios
        if pl.total_revenue > 0:
            ratios.gross_margin = (pl.gross_profit / pl.total_revenue) * 100
            ratios.operating_margin = (pl.operating_income / pl.total_revenue) * 100
            ratios.net_profit_margin = (pl.net_income / pl.total_revenue) * 100

        if bs.total_assets > 0:
            ratios.return_on_assets = (pl.net_income / bs.total_assets) * 100
            ratios.asset_turnover = pl.total_revenue / bs.total_assets

        if bs.total_equity > 0:
            ratios.return_on_equity = (pl.net_income / bs.total_equity) * 100

        # Leverage Ratios
        if bs.total_equity > 0:
            ratios.debt_to_equity = bs.total_liabilities / bs.total_equity

        if bs.total_assets > 0:
            ratios.debt_ratio = bs.total_liabilities / bs.total_assets
            ratios.equity_ratio = bs.total_equity / bs.total_assets

        # Working Capital
        ratios.working_capital = bs.current_assets - bs.current_liabilities

        return ratios

    # ========================================================================
    # TREND ANALYSIS
    # ========================================================================

    def generate_trend_analysis(
        self,
        organization_id: str,
        metric_name: str,
        period_type: str,  # "monthly", "quarterly", "yearly"
        start_date: date,
        end_date: date
    ) -> TrendAnalysis:
        """
        Generate trend analysis for a specific metric over time.

        Metrics can be:
        - "Revenue"
        - "Net Income"
        - "Gross Profit"
        - "Operating Expenses"
        - "Cash Balance"
        - etc.
        """
        trend = TrendAnalysis(
            organization_id=organization_id,
            metric_name=metric_name,
            period_type=period_type
        )

        # Generate periods
        periods = self._generate_periods(start_date, end_date, period_type)

        previous_value = None
        all_values = []

        for period_start, period_end, period_label in periods:
            # Get metric value for this period
            value = self._get_metric_value(
                organization_id,
                metric_name,
                period_start,
                period_end
            )

            all_values.append(value)

            # Calculate changes
            change_from_previous = None
            percent_change = None

            if previous_value is not None:
                change_from_previous = value - previous_value
                if previous_value != 0:
                    percent_change = (change_from_previous / previous_value) * 100

            data_point = TrendDataPoint(
                period=period_label,
                value=value,
                change_from_previous=change_from_previous,
                percent_change=percent_change
            )

            trend.data_points.append(data_point)
            previous_value = value

        # Calculate summary statistics
        if all_values:
            trend.total = sum(all_values)
            trend.average = trend.total / len(all_values)
            trend.min_value = min(all_values)
            trend.max_value = max(all_values)

            if len(all_values) >= 2:
                trend.overall_change = all_values[-1] - all_values[0]
                if all_values[0] != 0:
                    trend.overall_percent_change = (trend.overall_change / all_values[0]) * 100

        return trend

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _get_period_balance(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
        organization_id: str
    ) -> Decimal:
        """Get the net change in an account balance over a period."""
        # Get all journal entry lines for this account in the period
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(jel.debit), SUM(jel.credit)
            FROM journal_entry_lines jel
            JOIN journal_entries je ON jel.entry_id = je.entry_id
            WHERE jel.account_id = ?
            AND je.entry_date >= ?
            AND je.entry_date <= ?
            AND je.status = 'posted'
        """, (account_id, start_date.isoformat(), end_date.isoformat()))

        row = cursor.fetchone()
        conn.close()

        if row and row[0] is not None:
            total_debits = Decimal(str(row[0]))
            total_credits = Decimal(str(row[1]))

            # For revenue accounts (credit normal balance), we want credits - debits
            # For expense accounts (debit normal balance), we want debits - credits
            account = self.bookkeeper.get_account(account_id, organization_id)

            if account.account_type in [AccountType.REVENUE, AccountType.LIABILITY, AccountType.EQUITY]:
                return total_credits - total_debits
            else:
                return total_debits - total_credits

        return Decimal("0.00")

    def _get_balance_as_of(
        self,
        account_id: str,
        as_of_date: date,
        organization_id: str
    ) -> Decimal:
        """Get account balance as of a specific date."""
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(jel.debit), SUM(jel.credit)
            FROM journal_entry_lines jel
            JOIN journal_entries je ON jel.entry_id = je.entry_id
            WHERE jel.account_id = ?
            AND je.entry_date <= ?
            AND je.status = 'posted'
        """, (account_id, as_of_date.isoformat()))

        row = cursor.fetchone()
        conn.close()

        if row and row[0] is not None:
            total_debits = Decimal(str(row[0]))
            total_credits = Decimal(str(row[1]))

            account = self.bookkeeper.get_account(account_id, organization_id)

            # Assets and Expenses have debit normal balance
            if account.account_type in [AccountType.ASSET, AccountType.EXPENSE]:
                return total_debits - total_credits
            else:
                # Liabilities, Equity, Revenue have credit normal balance
                return total_credits - total_debits

        return Decimal("0.00")

    def _generate_periods(
        self,
        start_date: date,
        end_date: date,
        period_type: str
    ) -> List[Tuple[date, date, str]]:
        """Generate list of periods between start and end dates."""
        periods = []
        current = start_date

        while current <= end_date:
            if period_type == "monthly":
                # Monthly periods
                period_start = current

                # Last day of month
                if current.month == 12:
                    period_end = date(current.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end = date(current.year, current.month + 1, 1) - timedelta(days=1)

                if period_end > end_date:
                    period_end = end_date

                label = current.strftime("%Y-%m")

                periods.append((period_start, period_end, label))

                # Move to next month
                if current.month == 12:
                    current = date(current.year + 1, 1, 1)
                else:
                    current = date(current.year, current.month + 1, 1)

            elif period_type == "quarterly":
                # Quarterly periods
                quarter = (current.month - 1) // 3 + 1
                period_start = date(current.year, (quarter - 1) * 3 + 1, 1)

                if quarter == 4:
                    period_end = date(current.year, 12, 31)
                else:
                    period_end = date(current.year, quarter * 3 + 1, 1) - timedelta(days=1)

                if period_end > end_date:
                    period_end = end_date

                label = f"{current.year}-Q{quarter}"

                periods.append((period_start, period_end, label))

                # Move to next quarter
                if quarter == 4:
                    current = date(current.year + 1, 1, 1)
                else:
                    current = date(current.year, (quarter * 3) + 1, 1)

            elif period_type == "yearly":
                # Yearly periods
                period_start = date(current.year, 1, 1)
                period_end = date(current.year, 12, 31)

                if period_end > end_date:
                    period_end = end_date

                label = str(current.year)

                periods.append((period_start, period_end, label))

                # Move to next year
                current = date(current.year + 1, 1, 1)

            else:
                raise ValueError(f"Invalid period_type: {period_type}")

        return periods

    def _get_metric_value(
        self,
        organization_id: str,
        metric_name: str,
        period_start: date,
        period_end: date
    ) -> Decimal:
        """Get the value of a specific metric for a period."""
        metric_lower = metric_name.lower()

        if metric_lower == "revenue":
            pl = self.generate_profit_loss(organization_id, period_start, period_end)
            return pl.total_revenue

        elif metric_lower == "net income":
            pl = self.generate_profit_loss(organization_id, period_start, period_end)
            return pl.net_income

        elif metric_lower == "gross profit":
            pl = self.generate_profit_loss(organization_id, period_start, period_end)
            return pl.gross_profit

        elif metric_lower == "operating expenses":
            pl = self.generate_profit_loss(organization_id, period_start, period_end)
            return pl.total_operating_expenses

        elif metric_lower == "operating income":
            pl = self.generate_profit_loss(organization_id, period_start, period_end)
            return pl.operating_income

        elif metric_lower == "cash balance":
            # Get cash account balance as of period end
            accounts = self.bookkeeper.get_chart_of_accounts(organization_id)
            cash_accounts = [a for a in accounts if "cash" in a.account_name.lower()]
            if cash_accounts:
                return self._get_balance_as_of(cash_accounts[0].account_id, period_end, organization_id)
            return Decimal("0.00")

        else:
            # Default to 0 for unknown metrics
            return Decimal("0.00")

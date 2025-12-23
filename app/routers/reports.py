# app/routers/reports.py

"""
Financial Reports API
Generates income statements, balance sheets, and trial balances
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
import sqlite3
from datetime import datetime, date
from decimal import Decimal

from ..db import DB_PATH
from .auth import get_current_user_id

router = APIRouter(prefix="/api/reports", tags=["Reports"])


# =========================================================================
# MODELS
# =========================================================================

class AccountBalance(BaseModel):
    """Account balance line item"""
    account_code: str
    account_name: str
    account_type: str
    balance: float
    debit: Optional[float] = None
    credit: Optional[float] = None


class IncomeStatementResponse(BaseModel):
    """Income statement (P&L) report"""
    organization_id: str
    entity_id: Optional[str]
    start_date: str
    end_date: str
    revenue: List[AccountBalance]
    total_revenue: float
    expenses: List[AccountBalance]
    total_expenses: float
    net_income: float
    generated_at: str


class BalanceSheetResponse(BaseModel):
    """Balance sheet report"""
    organization_id: str
    entity_id: Optional[str]
    as_of_date: str
    assets: List[AccountBalance]
    total_assets: float
    liabilities: List[AccountBalance]
    total_liabilities: float
    equity: List[AccountBalance]
    total_equity: float
    generated_at: str


class TrialBalanceResponse(BaseModel):
    """Trial balance report"""
    organization_id: str
    entity_id: Optional[str]
    as_of_date: str
    accounts: List[AccountBalance]
    total_debits: float
    total_credits: float
    is_balanced: bool
    generated_at: str


class CashFlowStatementResponse(BaseModel):
    """Cash flow statement"""
    organization_id: str
    entity_id: Optional[str]
    start_date: str
    end_date: str
    operating_activities: List[AccountBalance]
    net_cash_from_operations: float
    investing_activities: List[AccountBalance]
    net_cash_from_investing: float
    financing_activities: List[AccountBalance]
    net_cash_from_financing: float
    net_change_in_cash: float
    beginning_cash: float
    ending_cash: float
    generated_at: str


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def get_account_balances(
    org_id: str,
    entity_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_types: Optional[List[str]] = None
) -> List[AccountBalance]:
    """Get account balances for specified criteria"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Build query
        query = """
            SELECT
                a.code as account_code,
                a.name as account_name,
                a.type as account_type,
                a.normal_balance,
                COALESCE(SUM(jel.debit), 0) as total_debit,
                COALESCE(SUM(jel.credit), 0) as total_credit
            FROM accounts a
            LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
            LEFT JOIN journal_entries je ON jel.entry_id = je.entry_id
            WHERE a.organization_id = ?
                AND je.status = 'posted'
        """
        params = [org_id]

        if entity_id:
            query += " AND a.entity_id = ?"
            params.append(entity_id)

        if start_date:
            query += " AND je.entry_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND je.entry_date <= ?"
            params.append(end_date)

        if account_types:
            placeholders = ", ".join("?" * len(account_types))
            query += f" AND a.type IN ({placeholders})"
            params.extend(account_types)

        query += """
            GROUP BY a.code, a.name, a.type, a.normal_balance
            HAVING (total_debit - total_credit) != 0 OR (total_credit - total_debit) != 0
            ORDER BY a.code ASC
        """

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        balances = []
        for row in rows:
            # Calculate balance based on normal balance
            if row["normal_balance"] == "debit":
                balance = row["total_debit"] - row["total_credit"]
            else:
                balance = row["total_credit"] - row["total_debit"]

            balances.append(AccountBalance(
                account_code=row["account_code"],
                account_name=row["account_name"],
                account_type=row["account_type"],
                balance=round(balance, 2),
                debit=round(row["total_debit"], 2),
                credit=round(row["total_credit"], 2)
            ))

        return balances


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/income-statement", response_model=IncomeStatementResponse)
async def get_income_statement(
    org_id: str,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Generate Income Statement (Profit & Loss)

    Shows revenue and expenses for a date range
    """
    try:
        # Get revenue accounts
        revenue_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Income", "Revenue"]
        )
        total_revenue = sum(acc.balance for acc in revenue_accounts)

        # Get expense accounts
        expense_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Expense", "Cost of Goods Sold"]
        )
        total_expenses = sum(acc.balance for acc in expense_accounts)

        # Calculate net income
        net_income = total_revenue - total_expenses

        return IncomeStatementResponse(
            organization_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            revenue=revenue_accounts,
            total_revenue=round(total_revenue, 2),
            expenses=expense_accounts,
            total_expenses=round(total_expenses, 2),
            net_income=round(net_income, 2),
            generated_at=datetime.now().isoformat()
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate income statement: {str(e)}"
        )


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    org_id: str,
    as_of_date: str = Query(..., description="As of date (YYYY-MM-DD)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Generate Balance Sheet

    Shows assets, liabilities, and equity as of a specific date
    """
    try:
        # Get asset accounts
        asset_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            end_date=as_of_date,
            account_types=["Asset", "Current Asset", "Fixed Asset", "Other Asset"]
        )
        total_assets = sum(acc.balance for acc in asset_accounts)

        # Get liability accounts
        liability_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            end_date=as_of_date,
            account_types=["Liability", "Current Liability", "Long-Term Liability"]
        )
        total_liabilities = sum(acc.balance for acc in liability_accounts)

        # Get equity accounts
        equity_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            end_date=as_of_date,
            account_types=["Equity", "Owner's Equity"]
        )
        total_equity = sum(acc.balance for acc in equity_accounts)

        return BalanceSheetResponse(
            organization_id=org_id,
            entity_id=entity_id,
            as_of_date=as_of_date,
            assets=asset_accounts,
            total_assets=round(total_assets, 2),
            liabilities=liability_accounts,
            total_liabilities=round(total_liabilities, 2),
            equity=equity_accounts,
            total_equity=round(total_equity, 2),
            generated_at=datetime.now().isoformat()
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate balance sheet: {str(e)}"
        )


@router.get("/trial-balance", response_model=TrialBalanceResponse)
async def get_trial_balance(
    org_id: str,
    as_of_date: str = Query(..., description="As of date (YYYY-MM-DD)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Generate Trial Balance

    Lists all accounts with debit and credit totals
    Verifies that total debits equal total credits
    """
    try:
        # Get all accounts with balances
        accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            end_date=as_of_date
        )

        # Calculate totals
        total_debits = sum(acc.debit or 0 for acc in accounts)
        total_credits = sum(acc.credit or 0 for acc in accounts)

        # Check if balanced (allow small rounding differences)
        is_balanced = abs(total_debits - total_credits) < 0.01

        return TrialBalanceResponse(
            organization_id=org_id,
            entity_id=entity_id,
            as_of_date=as_of_date,
            accounts=accounts,
            total_debits=round(total_debits, 2),
            total_credits=round(total_credits, 2),
            is_balanced=is_balanced,
            generated_at=datetime.now().isoformat()
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate trial balance: {str(e)}"
        )


@router.get("/cash-flow", response_model=CashFlowStatementResponse)
async def get_cash_flow_statement(
    org_id: str,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Generate Cash Flow Statement

    Shows cash flows from operating, investing, and financing activities
    """
    try:
        # This is a simplified version - in practice, cash flow statements
        # require more detailed categorization of transactions

        # Get cash/bank account balance at start
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT COALESCE(SUM(jel.debit - jel.credit), 0) as balance
                FROM journal_entry_lines jel
                JOIN journal_entries je ON jel.entry_id = je.entry_id
                JOIN accounts a ON jel.account_code = a.code
                WHERE a.organization_id = ?
                    AND a.type IN ('Asset', 'Current Asset')
                    AND a.name LIKE '%Cash%' OR a.name LIKE '%Bank%'
                    AND je.entry_date < ?
                    AND je.status = 'posted'
            """, (org_id, start_date))
            beginning_cash = cursor.fetchone()[0] or 0.0

        # Operating activities (simplified - use income statement items)
        revenue_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Income", "Revenue"]
        )

        expense_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Expense", "Cost of Goods Sold"]
        )

        operating_activities = revenue_accounts + expense_accounts
        net_cash_from_operations = sum(acc.balance for acc in revenue_accounts) - sum(acc.balance for acc in expense_accounts)

        # Investing activities (asset purchases/sales)
        investing_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Fixed Asset", "Other Asset"]
        )
        net_cash_from_investing = -sum(acc.balance for acc in investing_accounts)  # Negative for purchases

        # Financing activities (loans, equity)
        financing_accounts = get_account_balances(
            org_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            account_types=["Long-Term Liability", "Equity"]
        )
        net_cash_from_financing = sum(acc.balance for acc in financing_accounts)

        # Calculate net change
        net_change = net_cash_from_operations + net_cash_from_investing + net_cash_from_financing
        ending_cash = beginning_cash + net_change

        return CashFlowStatementResponse(
            organization_id=org_id,
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            operating_activities=operating_activities,
            net_cash_from_operations=round(net_cash_from_operations, 2),
            investing_activities=investing_accounts,
            net_cash_from_investing=round(net_cash_from_investing, 2),
            financing_activities=financing_accounts,
            net_cash_from_financing=round(net_cash_from_financing, 2),
            net_change_in_cash=round(net_change, 2),
            beginning_cash=round(beginning_cash, 2),
            ending_cash=round(ending_cash, 2),
            generated_at=datetime.now().isoformat()
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate cash flow statement: {str(e)}"
        )


@router.get("/summary")
async def get_financial_summary(
    org_id: str,
    as_of_date: str = Query(..., description="As of date (YYYY-MM-DD)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get financial summary dashboard

    Provides key metrics at a glance
    """
    try:
        # Calculate metrics using existing endpoints
        # Get current month dates
        as_of = datetime.fromisoformat(as_of_date).date()
        start_of_month = as_of.replace(day=1).isoformat()

        # Get month-to-date income statement
        income_stmt = await get_income_statement(
            org_id=org_id,
            start_date=start_of_month,
            end_date=as_of_date,
            entity_id=entity_id,
            current_user_id=current_user_id
        )

        # Get balance sheet
        balance_sheet = await get_balance_sheet(
            org_id=org_id,
            as_of_date=as_of_date,
            entity_id=entity_id,
            current_user_id=current_user_id
        )

        # Calculate key ratios
        current_ratio = None
        if balance_sheet.total_liabilities > 0:
            current_ratio = round(balance_sheet.total_assets / balance_sheet.total_liabilities, 2)

        profit_margin = None
        if income_stmt.total_revenue > 0:
            profit_margin = round((income_stmt.net_income / income_stmt.total_revenue) * 100, 2)

        return {
            "organization_id": org_id,
            "entity_id": entity_id,
            "as_of_date": as_of_date,
            "metrics": {
                "total_revenue": income_stmt.total_revenue,
                "total_expenses": income_stmt.total_expenses,
                "net_income": income_stmt.net_income,
                "total_assets": balance_sheet.total_assets,
                "total_liabilities": balance_sheet.total_liabilities,
                "total_equity": balance_sheet.total_equity,
                "profit_margin_percent": profit_margin,
                "current_ratio": current_ratio
            },
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate financial summary: {str(e)}"
        )


@router.post("/generate")
async def generate_report(
    org_id: str,
    report_type: str = Query(..., description="Type of report: income-statement, balance-sheet, trial-balance, cash-flow, summary"),
    start_date: Optional[str] = Query(None, description="Start date (for income statement, cash flow)"),
    end_date: Optional[str] = Query(None, description="End date (for income statement, cash flow)"),
    as_of_date: Optional[str] = Query(None, description="As of date (for balance sheet, trial balance)"),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Generic report generation endpoint

    Routes to specific report types based on report_type parameter
    Compatible with frontend's generic /api/reports/generate call
    """
    try:
        # Route to appropriate report handler
        if report_type == "income-statement":
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="start_date and end_date required for income statement"
                )
            return await get_income_statement(org_id, start_date, end_date, entity_id, current_user_id)

        elif report_type == "balance-sheet":
            if not as_of_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="as_of_date required for balance sheet"
                )
            return await get_balance_sheet(org_id, as_of_date, entity_id, current_user_id)

        elif report_type == "trial-balance":
            if not as_of_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="as_of_date required for trial balance"
                )
            return await get_trial_balance(org_id, as_of_date, entity_id, current_user_id)

        elif report_type == "cash-flow":
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="start_date and end_date required for cash flow statement"
                )
            return await get_cash_flow_statement(org_id, start_date, end_date, entity_id, current_user_id)

        elif report_type == "summary":
            if not as_of_date:
                # Default to today
                as_of_date = datetime.now().date().isoformat()
            return await get_financial_summary(org_id, as_of_date, entity_id, current_user_id)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid report_type: {report_type}. Must be one of: income-statement, balance-sheet, trial-balance, cash-flow, summary"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}"
        )

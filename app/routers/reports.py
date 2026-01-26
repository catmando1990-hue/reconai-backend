# app/routers/reports.py

"""
Financial Reports API
Generates income statements, balance sheets, trial balances, and
advanced analytics reports (recurring activity, balance history,
reconciliation, data integrity).

Phase 1 Additions:
- GET /api/reports/recurring - Recurring activity detection
- GET /api/reports/balance-history - Daily balance rollups
- POST /api/reports/reconciliation - Statement vs ledger matching
- GET /api/reports/data-integrity - Duplicate/missing data checks
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query, Body
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal, Any
import sqlite3
import hashlib
import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from uuid import uuid4
from collections import defaultdict

from ..db import DB_PATH
from app.auth_context import get_current_context, get_current_organization_id, get_current_user_id, AuthContext

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
    org_id: str = Depends(get_current_organization_id),
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
    org_id: str = Depends(get_current_organization_id),
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
    org_id: str = Depends(get_current_organization_id),
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
    org_id: str = Depends(get_current_organization_id),
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
    org_id: str = Depends(get_current_organization_id),
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
    org_id: str = Depends(get_current_organization_id),
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


# =========================================================================
# PHASE 1: CORE REPORTS - NEW MODELS
# =========================================================================

class RecurringPattern(BaseModel):
    """Detected recurring transaction pattern"""
    merchant_normalized: str
    pattern_type: Literal["weekly", "monthly", "quarterly", "annual", "custom"]
    interval_days: int
    occurrences: int
    avg_amount: float
    min_amount: float
    max_amount: float
    first_seen: str
    last_seen: str
    next_expected: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str]  # Transaction IDs


class RecurringActivityResponse(BaseModel):
    """Response for recurring activity detection"""
    organization_id: str
    start_date: str
    end_date: str
    patterns: List[RecurringPattern]
    total_recurring_amount: float
    generated_at: str
    request_id: str


class BalanceHistoryEntry(BaseModel):
    """Single day balance entry"""
    date: str
    opening_balance: float
    deposits: float
    withdrawals: float
    closing_balance: float
    transaction_count: int


class BalanceHistoryResponse(BaseModel):
    """Response for balance history report"""
    organization_id: str
    account_ids: Optional[List[str]]
    start_date: str
    end_date: str
    entries: List[BalanceHistoryEntry]
    period_summary: Dict[str, float]
    generated_at: str
    request_id: str


class ReconciliationItem(BaseModel):
    """Single reconciliation comparison item"""
    date: str
    statement_amount: float
    ledger_amount: float
    variance: float
    status: Literal["matched", "discrepancy", "missing_statement", "missing_ledger"]
    evidence: Optional[Dict[str, Any]] = None


class ReconciliationRequest(BaseModel):
    """Request for statement reconciliation"""
    bank_statement: List[Dict[str, Any]] = Field(..., description="Bank statement entries: [{date, description, amount}]")
    ledger_snapshot: List[Dict[str, Any]] = Field(..., description="Ledger entries: [{date, description, amount, account_code}]")
    tolerance: float = Field(default=0.01, description="Matching tolerance for amounts")
    evidence: Dict[str, Any] = Field(
        ...,
        description="Evidence attachment required (statement_source, ledger_export_timestamp, reconciler)"
    )


class ReconciliationResponse(BaseModel):
    """Response for reconciliation report"""
    organization_id: str
    period_start: str
    period_end: str
    items: List[ReconciliationItem]
    summary: Dict[str, Any]
    discrepancies: List[Dict[str, Any]]
    generated_at: str
    request_id: str


class DataIntegrityIssue(BaseModel):
    """Single data integrity issue"""
    issue_type: Literal["duplicate", "missing_date", "orphaned", "invalid_amount", "sequence_gap"]
    severity: Literal["info", "warning", "error", "critical"]
    description: str
    affected_records: List[str]
    suggested_action: Optional[str] = None


class DataIntegrityResponse(BaseModel):
    """Response for data integrity report"""
    organization_id: str
    scan_date: str
    issues: List[DataIntegrityIssue]
    summary: Dict[str, int]
    health_score: float = Field(ge=0.0, le=100.0)
    generated_at: str
    request_id: str


# =========================================================================
# PHASE 1: CORE REPORTS - NEW HELPER FUNCTIONS
# =========================================================================

def _generate_request_id() -> str:
    """Generate unique request ID for audit trail"""
    return f"req_{uuid4().hex[:12]}"


def _detect_recurring_patterns(
    transactions: List[Dict],
    min_occurrences: int = 3,
    min_confidence: float = 0.85
) -> List[RecurringPattern]:
    """
    Detect recurring transaction patterns.
    Groups by merchant and analyzes intervals.
    """
    patterns = []

    # Group transactions by normalized merchant
    by_merchant: Dict[str, List[Dict]] = defaultdict(list)
    for tx in transactions:
        merchant = (tx.get("merchant_normalized") or tx.get("merchant_name") or "").strip().lower()
        if merchant:
            by_merchant[merchant].append(tx)

    for merchant, txs in by_merchant.items():
        if len(txs) < min_occurrences:
            continue

        # Sort by date
        sorted_txs = sorted(txs, key=lambda x: x.get("date", ""))

        # Calculate intervals between transactions
        dates = [datetime.fromisoformat(tx["date"]).date() for tx in sorted_txs if tx.get("date")]
        if len(dates) < min_occurrences:
            continue

        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)

        # Determine pattern type
        pattern_type = "custom"
        if 5 <= avg_interval <= 9:
            pattern_type = "weekly"
        elif 27 <= avg_interval <= 33:
            pattern_type = "monthly"
        elif 85 <= avg_interval <= 95:
            pattern_type = "quarterly"
        elif 360 <= avg_interval <= 370:
            pattern_type = "annual"

        # Calculate confidence based on interval consistency
        if len(intervals) > 1:
            interval_variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
            interval_std = interval_variance ** 0.5
            # Lower std = higher confidence
            confidence = max(0.0, min(1.0, 1.0 - (interval_std / avg_interval) if avg_interval > 0 else 0))
        else:
            confidence = 0.5

        if confidence < min_confidence:
            continue

        amounts = [abs(tx.get("amount", 0)) for tx in sorted_txs]

        # Calculate next expected date
        next_expected = None
        if dates:
            next_date = dates[-1] + timedelta(days=int(avg_interval))
            next_expected = next_date.isoformat()

        patterns.append(RecurringPattern(
            merchant_normalized=merchant,
            pattern_type=pattern_type,
            interval_days=int(avg_interval),
            occurrences=len(sorted_txs),
            avg_amount=sum(amounts) / len(amounts),
            min_amount=min(amounts),
            max_amount=max(amounts),
            first_seen=dates[0].isoformat() if dates else "",
            last_seen=dates[-1].isoformat() if dates else "",
            next_expected=next_expected,
            confidence=round(confidence, 3),
            evidence=[tx.get("id", "") for tx in sorted_txs]
        ))

    # Sort by confidence descending
    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns


def _build_balance_history(
    transactions: List[Dict],
    start_date: date,
    end_date: date,
    opening_balance: float = 0.0
) -> List[BalanceHistoryEntry]:
    """Build daily balance history from transactions"""
    entries = []

    # Group transactions by date
    by_date: Dict[str, List[Dict]] = defaultdict(list)
    for tx in transactions:
        tx_date = tx.get("date", "")[:10]  # Get YYYY-MM-DD
        if tx_date:
            by_date[tx_date].append(tx)

    current_balance = opening_balance
    current_date = start_date

    while current_date <= end_date:
        date_str = current_date.isoformat()
        day_txs = by_date.get(date_str, [])

        deposits = sum(tx.get("amount", 0) for tx in day_txs if tx.get("amount", 0) > 0)
        withdrawals = sum(abs(tx.get("amount", 0)) for tx in day_txs if tx.get("amount", 0) < 0)

        opening = current_balance
        closing = opening + deposits - withdrawals

        entries.append(BalanceHistoryEntry(
            date=date_str,
            opening_balance=round(opening, 2),
            deposits=round(deposits, 2),
            withdrawals=round(withdrawals, 2),
            closing_balance=round(closing, 2),
            transaction_count=len(day_txs)
        ))

        current_balance = closing
        current_date += timedelta(days=1)

    return entries


def _check_data_integrity(org_id: str) -> List[DataIntegrityIssue]:
    """Run data integrity checks on organization data"""
    issues = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Check 1: Duplicate transactions (same date, amount, merchant)
        cursor = conn.execute("""
            SELECT date, amount, merchant_normalized, COUNT(*) as cnt,
                   GROUP_CONCAT(id) as ids
            FROM core_transactions
            WHERE organization_id = ?
            GROUP BY date, amount, merchant_normalized
            HAVING cnt > 1
        """, (org_id,))

        for row in cursor.fetchall():
            issues.append(DataIntegrityIssue(
                issue_type="duplicate",
                severity="warning",
                description=f"Duplicate transactions on {row['date']}: amount={row['amount']}, merchant={row['merchant_normalized']}",
                affected_records=row['ids'].split(",") if row['ids'] else [],
                suggested_action="Review and remove duplicate entries"
            ))

        # Check 2: Missing dates (gaps in transaction sequence)
        cursor = conn.execute("""
            SELECT MIN(date) as min_date, MAX(date) as max_date
            FROM core_transactions
            WHERE organization_id = ?
        """, (org_id,))
        date_range = cursor.fetchone()

        if date_range and date_range['min_date'] and date_range['max_date']:
            cursor = conn.execute("""
                SELECT DISTINCT date FROM core_transactions
                WHERE organization_id = ?
                ORDER BY date
            """, (org_id,))
            dates = set(row['date'] for row in cursor.fetchall())

            # Check for gaps > 7 days
            if len(dates) >= 2:
                sorted_dates = sorted(dates)
                for i in range(len(sorted_dates) - 1):
                    try:
                        d1 = datetime.fromisoformat(sorted_dates[i]).date()
                        d2 = datetime.fromisoformat(sorted_dates[i+1]).date()
                        gap = (d2 - d1).days
                        if gap > 7:
                            issues.append(DataIntegrityIssue(
                                issue_type="missing_date",
                                severity="info",
                                description=f"Gap of {gap} days between {d1} and {d2}",
                                affected_records=[],
                                suggested_action="Verify no transactions are missing for this period"
                            ))
                    except (ValueError, TypeError):
                        continue

        # Check 3: Invalid amounts (zero or null)
        cursor = conn.execute("""
            SELECT id, date, name FROM core_transactions
            WHERE organization_id = ? AND (amount IS NULL OR amount = 0)
        """, (org_id,))

        invalid_amounts = cursor.fetchall()
        if invalid_amounts:
            issues.append(DataIntegrityIssue(
                issue_type="invalid_amount",
                severity="error",
                description=f"Found {len(invalid_amounts)} transactions with zero or null amounts",
                affected_records=[row['id'] for row in invalid_amounts],
                suggested_action="Review and correct transaction amounts"
            ))

        # Check 4: Orphaned transactions (no linked account)
        cursor = conn.execute("""
            SELECT id FROM core_transactions
            WHERE organization_id = ? AND account_id IS NULL
        """, (org_id,))

        orphaned = cursor.fetchall()
        if orphaned:
            issues.append(DataIntegrityIssue(
                issue_type="orphaned",
                severity="warning",
                description=f"Found {len(orphaned)} transactions without linked accounts",
                affected_records=[row['id'] for row in orphaned],
                suggested_action="Link transactions to appropriate accounts"
            ))

    return issues


# =========================================================================
# PHASE 1: CORE REPORTS - NEW ENDPOINTS
# =========================================================================

@router.get("/recurring", response_model=RecurringActivityResponse)
async def get_recurring_activity(
    ctx: AuthContext = Depends(get_current_context),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    min_occurrences: int = Query(3, ge=2, description="Minimum occurrences to qualify as recurring"),
    min_confidence: float = Query(0.85, ge=0.0, le=1.0, description="Minimum confidence threshold")
):
    """
    Detect recurring transactions (weekly/monthly/custom)

    READ-ONLY endpoint. Returns patterns with confidence >= 0.85 by default.
    Evidence list includes transaction IDs for audit trail.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            cursor = conn.execute("""
                SELECT id, date, amount, name, merchant_name, merchant_normalized
                FROM core_transactions
                WHERE organization_id = ?
                  AND date >= ? AND date <= ?
                ORDER BY date ASC
            """, (org_id, start_date, end_date))

            transactions = [dict(row) for row in cursor.fetchall()]

        patterns = _detect_recurring_patterns(
            transactions,
            min_occurrences=min_occurrences,
            min_confidence=min_confidence
        )

        total_recurring = sum(p.avg_amount * p.occurrences for p in patterns)

        return RecurringActivityResponse(
            organization_id=org_id,
            start_date=start_date,
            end_date=end_date,
            patterns=patterns,
            total_recurring_amount=round(total_recurring, 2),
            generated_at=datetime.utcnow().isoformat(),
            request_id=request_id
        )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )


@router.get("/balance-history", response_model=BalanceHistoryResponse)
async def get_balance_history(
    ctx: AuthContext = Depends(get_current_context),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    account_ids: Optional[str] = Query(None, description="Comma-separated account IDs (optional)")
):
    """
    Get daily balance rollups for specified date range.

    READ-ONLY endpoint. Returns opening/closing balances per day.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    try:
        parsed_start = datetime.fromisoformat(start_date).date()
        parsed_end = datetime.fromisoformat(end_date).date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_DATE", "message": "Dates must be YYYY-MM-DD", "request_id": request_id}
        )

    if parsed_end < parsed_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_RANGE", "message": "end_date must be >= start_date", "request_id": request_id}
        )

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Build query
            query = """
                SELECT id, date, amount, name, account_id
                FROM core_transactions
                WHERE organization_id = ?
                  AND date >= ? AND date <= ?
            """
            params = [org_id, start_date, end_date]

            if account_ids:
                ids_list = [a.strip() for a in account_ids.split(",")]
                placeholders = ",".join("?" * len(ids_list))
                query += f" AND account_id IN ({placeholders})"
                params.extend(ids_list)

            query += " ORDER BY date ASC"

            cursor = conn.execute(query, params)
            transactions = [dict(row) for row in cursor.fetchall()]

        entries = _build_balance_history(transactions, parsed_start, parsed_end)

        # Calculate period summary
        total_deposits = sum(e.deposits for e in entries)
        total_withdrawals = sum(e.withdrawals for e in entries)

        return BalanceHistoryResponse(
            organization_id=org_id,
            account_ids=account_ids.split(",") if account_ids else None,
            start_date=start_date,
            end_date=end_date,
            entries=entries,
            period_summary={
                "total_deposits": round(total_deposits, 2),
                "total_withdrawals": round(total_withdrawals, 2),
                "net_change": round(total_deposits - total_withdrawals, 2),
                "opening_balance": entries[0].opening_balance if entries else 0,
                "closing_balance": entries[-1].closing_balance if entries else 0
            },
            generated_at=datetime.utcnow().isoformat(),
            request_id=request_id
        )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )


@router.post("/reconciliation", response_model=ReconciliationResponse)
async def run_reconciliation(
    data: ReconciliationRequest,
    ctx: AuthContext = Depends(get_current_context)
):
    """
    Compare bank statement to ledger and identify discrepancies.

    Accepts bank_statement and ledger_snapshot arrays.
    Returns matched items and discrepancies.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    if not data.bank_statement:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "EMPTY_STATEMENT", "message": "bank_statement is required", "request_id": request_id}
        )

    if not data.ledger_snapshot:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "EMPTY_LEDGER", "message": "ledger_snapshot is required", "request_id": request_id}
        )

    items = []
    discrepancies = []

    # Create lookup for ledger entries
    ledger_by_key: Dict[str, List[Dict]] = defaultdict(list)
    for entry in data.ledger_snapshot:
        key = f"{entry.get('date', '')}_{abs(entry.get('amount', 0)):.2f}"
        ledger_by_key[key].append(entry)

    matched_ledger_indices = set()

    # Match statement to ledger
    for stmt in data.bank_statement:
        stmt_date = stmt.get("date", "")
        stmt_amount = stmt.get("amount", 0)
        stmt_key = f"{stmt_date}_{abs(stmt_amount):.2f}"

        matched = False
        for idx, ledger in enumerate(ledger_by_key.get(stmt_key, [])):
            ledger_amount = ledger.get("amount", 0)
            variance = abs(stmt_amount - ledger_amount)

            if variance <= data.tolerance:
                items.append(ReconciliationItem(
                    date=stmt_date,
                    statement_amount=stmt_amount,
                    ledger_amount=ledger_amount,
                    variance=round(variance, 2),
                    status="matched",
                    evidence={"statement": stmt, "ledger": ledger}
                ))
                matched_ledger_indices.add(f"{stmt_key}_{idx}")
                matched = True
                break

        if not matched:
            items.append(ReconciliationItem(
                date=stmt_date,
                statement_amount=stmt_amount,
                ledger_amount=0.0,
                variance=abs(stmt_amount),
                status="missing_ledger",
                evidence={"statement": stmt}
            ))
            discrepancies.append({
                "type": "missing_ledger",
                "date": stmt_date,
                "amount": stmt_amount,
                "description": stmt.get("description", "")
            })

    # Find ledger entries with no matching statement
    for key, entries in ledger_by_key.items():
        for idx, ledger in enumerate(entries):
            if f"{key}_{idx}" not in matched_ledger_indices:
                items.append(ReconciliationItem(
                    date=ledger.get("date", ""),
                    statement_amount=0.0,
                    ledger_amount=ledger.get("amount", 0),
                    variance=abs(ledger.get("amount", 0)),
                    status="missing_statement",
                    evidence={"ledger": ledger}
                ))
                discrepancies.append({
                    "type": "missing_statement",
                    "date": ledger.get("date", ""),
                    "amount": ledger.get("amount", 0),
                    "description": ledger.get("description", "")
                })

    # Sort items by date
    items.sort(key=lambda x: x.date)

    # Calculate dates
    all_dates = [i.date for i in items if i.date]
    period_start = min(all_dates) if all_dates else ""
    period_end = max(all_dates) if all_dates else ""

    matched_count = sum(1 for i in items if i.status == "matched")

    return ReconciliationResponse(
        organization_id=org_id,
        period_start=period_start,
        period_end=period_end,
        items=items,
        summary={
            "total_items": len(items),
            "matched": matched_count,
            "discrepancies": len(discrepancies),
            "match_rate": round(matched_count / len(items) * 100, 2) if items else 0,
            "statement_total": sum(s.get("amount", 0) for s in data.bank_statement),
            "ledger_total": sum(l.get("amount", 0) for l in data.ledger_snapshot)
        },
        discrepancies=discrepancies,
        generated_at=datetime.utcnow().isoformat(),
        request_id=request_id
    )


@router.get("/data-integrity", response_model=DataIntegrityResponse)
async def get_data_integrity(
    ctx: AuthContext = Depends(get_current_context)
):
    """
    Run data integrity checks on organization data.

    READ-ONLY endpoint. Identifies duplicates, missing data, orphaned records.
    Returns health score (0-100) based on issue severity.
    """
    request_id = _generate_request_id()
    org_id = ctx["org_id"]

    try:
        issues = _check_data_integrity(org_id)

        # Count by severity
        severity_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for issue in issues:
            severity_counts[issue.severity] += 1

        # Calculate health score
        # Critical = -20, Error = -10, Warning = -5, Info = -1
        penalty = (
            severity_counts["critical"] * 20 +
            severity_counts["error"] * 10 +
            severity_counts["warning"] * 5 +
            severity_counts["info"] * 1
        )
        health_score = max(0.0, 100.0 - penalty)

        return DataIntegrityResponse(
            organization_id=org_id,
            scan_date=datetime.utcnow().date().isoformat(),
            issues=issues,
            summary={
                "total_issues": len(issues),
                "critical": severity_counts["critical"],
                "errors": severity_counts["error"],
                "warnings": severity_counts["warning"],
                "info": severity_counts["info"]
            },
            health_score=round(health_score, 1),
            generated_at=datetime.utcnow().isoformat(),
            request_id=request_id
        )

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "DATABASE_ERROR", "message": str(e), "request_id": request_id}
        )

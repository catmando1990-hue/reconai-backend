# app/bookkeeping/models.py

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class AccountType(str, Enum):
    """
    Five fundamental account types in accounting.
    Determines normal balance (debit or credit).
    """
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    REVENUE = "Revenue"
    EXPENSE = "Expense"


class AccountSubtype(str, Enum):
    """Detailed account subtypes for classification"""
    # Assets
    CASH = "Cash"
    BANK = "Bank"
    ACCOUNTS_RECEIVABLE = "Accounts Receivable"
    INVENTORY = "Inventory"
    PREPAID_EXPENSES = "Prepaid Expenses"
    FIXED_ASSETS = "Fixed Assets"
    ACCUMULATED_DEPRECIATION = "Accumulated Depreciation"
    OTHER_CURRENT_ASSETS = "Other Current Assets"
    OTHER_ASSETS = "Other Assets"

    # Liabilities
    ACCOUNTS_PAYABLE = "Accounts Payable"
    CREDIT_CARD = "Credit Card"
    LOANS_PAYABLE = "Loans Payable"
    ACCRUED_EXPENSES = "Accrued Expenses"
    DEFERRED_REVENUE = "Deferred Revenue"
    OTHER_CURRENT_LIABILITIES = "Other Current Liabilities"
    LONG_TERM_LIABILITIES = "Long-term Liabilities"

    # Equity
    OWNERS_EQUITY = "Owner's Equity"
    RETAINED_EARNINGS = "Retained Earnings"
    DRAWS = "Owner Draws"
    CAPITAL_STOCK = "Capital Stock"

    # Revenue
    SALES_REVENUE = "Sales Revenue"
    SERVICE_REVENUE = "Service Revenue"
    OTHER_INCOME = "Other Income"
    INTEREST_INCOME = "Interest Income"

    # Expenses
    COST_OF_GOODS_SOLD = "Cost of Goods Sold"
    OPERATING_EXPENSES = "Operating Expenses"
    PAYROLL_EXPENSES = "Payroll Expenses"
    RENT_EXPENSE = "Rent Expense"
    UTILITIES_EXPENSE = "Utilities Expense"
    INSURANCE_EXPENSE = "Insurance Expense"
    DEPRECIATION_EXPENSE = "Depreciation Expense"
    INTEREST_EXPENSE = "Interest Expense"
    TAX_EXPENSE = "Tax Expense"
    OTHER_EXPENSES = "Other Expenses"


class NormalBalance(str, Enum):
    """Normal balance side for account types"""
    DEBIT = "Debit"
    CREDIT = "Credit"


# Mapping of account types to their normal balance
NORMAL_BALANCE_MAP = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


class Account(BaseModel):
    """
    Chart of Accounts - Individual account record.

    Follows standard accounting numbering:
    - 1000-1999: Assets
    - 2000-2999: Liabilities
    - 3000-3999: Equity
    - 4000-4999: Revenue
    - 5000-5999: Expenses
    """
    account_id: str = Field(..., description="Unique account identifier (e.g., '1000', '4010')")
    account_number: str = Field(..., description="Account number for sorting/display")
    account_name: str = Field(..., description="Account name (e.g., 'Cash', 'Sales Revenue')")
    account_type: AccountType = Field(..., description="Asset/Liability/Equity/Revenue/Expense")
    account_subtype: Optional[AccountSubtype] = Field(None, description="Detailed classification")
    description: Optional[str] = Field(None, description="Account description/purpose")
    normal_balance: NormalBalance = Field(..., description="Debit or Credit")
    is_active: bool = Field(True, description="Whether account is active")
    parent_account_id: Optional[str] = Field(None, description="Parent account for sub-accounts")
    current_balance: Decimal = Field(Decimal("0.00"), description="Current account balance")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator('current_balance', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v

    def get_normal_balance(self) -> NormalBalance:
        """Get the normal balance for this account type"""
        return NORMAL_BALANCE_MAP[self.account_type]

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "1000",
                "account_number": "1000",
                "account_name": "Cash - Operating",
                "account_type": "Asset",
                "account_subtype": "Cash",
                "description": "Primary operating cash account",
                "normal_balance": "Debit",
                "is_active": True,
                "current_balance": "25000.00"
            }
        }


class JournalEntryLine(BaseModel):
    """
    Individual line in a journal entry.
    Each entry must have at least one debit and one credit line.
    """
    line_id: Optional[str] = Field(None, description="Unique line identifier")
    account_id: str = Field(..., description="Account being debited/credited")
    account_name: Optional[str] = Field(None, description="Account name (for display)")
    debit: Decimal = Field(Decimal("0.00"), description="Debit amount")
    credit: Decimal = Field(Decimal("0.00"), description="Credit amount")
    memo: Optional[str] = Field(None, description="Line-level memo/description")

    @field_validator('debit', 'credit', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v

    @field_validator('debit', 'credit')
    @classmethod
    def validate_amounts(cls, v):
        if v < 0:
            raise ValueError("Debit and credit amounts must be non-negative")
        return v

    def validate_debit_credit_exclusive(self) -> bool:
        """A line must have either a debit OR credit, not both, not neither"""
        has_debit = self.debit > 0
        has_credit = self.credit > 0
        return has_debit != has_credit  # XOR operation

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "1000",
                "account_name": "Cash - Operating",
                "debit": "1000.00",
                "credit": "0.00",
                "memo": "Payment received from customer"
            }
        }


class JournalEntry(BaseModel):
    """
    Complete journal entry with multiple lines.
    Implements double-entry bookkeeping: debits must equal credits.
    """
    entry_id: Optional[str] = Field(None, description="Unique entry identifier")
    entry_number: Optional[str] = Field(None, description="Human-readable entry number (e.g., 'JE-2024-001')")
    entry_date: date = Field(..., description="Transaction date")
    description: str = Field(..., description="Entry description/purpose")
    reference: Optional[str] = Field(None, description="Reference number (invoice, check, etc.)")
    lines: List[JournalEntryLine] = Field(..., min_length=2, description="Entry lines (min 2)")
    status: Literal["draft", "posted", "voided"] = Field("draft", description="Entry status")
    created_by: Optional[str] = Field(None, description="User who created entry")
    created_at: datetime = Field(default_factory=datetime.now)
    posted_at: Optional[datetime] = Field(None, description="When entry was posted")

    def total_debits(self) -> Decimal:
        """Calculate total debits"""
        return sum(line.debit for line in self.lines)

    def total_credits(self) -> Decimal:
        """Calculate total credits"""
        return sum(line.credit for line in self.lines)

    def is_balanced(self) -> bool:
        """Check if debits equal credits"""
        return self.total_debits() == self.total_credits()

    def validate_entry(self) -> tuple[bool, List[str]]:
        """
        Validate journal entry for posting.

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # Rule 1: Must have at least 2 lines
        if len(self.lines) < 2:
            errors.append("Journal entry must have at least 2 lines")

        # Rule 2: Each line must have debit XOR credit
        for i, line in enumerate(self.lines):
            if not line.validate_debit_credit_exclusive():
                errors.append(f"Line {i+1}: Must have either debit OR credit, not both or neither")

        # Rule 3: Debits must equal credits
        if not self.is_balanced():
            errors.append(
                f"Entry is not balanced: Debits={self.total_debits()}, Credits={self.total_credits()}"
            )

        # Rule 4: All lines must reference valid accounts
        if any(not line.account_id for line in self.lines):
            errors.append("All lines must have a valid account_id")

        return len(errors) == 0, errors

    class Config:
        json_schema_extra = {
            "example": {
                "entry_date": "2024-01-15",
                "description": "Payment received from Client ABC",
                "reference": "INV-2024-001",
                "lines": [
                    {
                        "account_id": "1000",
                        "account_name": "Cash",
                        "debit": "1000.00",
                        "credit": "0.00",
                        "memo": "Payment received"
                    },
                    {
                        "account_id": "4000",
                        "account_name": "Service Revenue",
                        "debit": "0.00",
                        "credit": "1000.00",
                        "memo": "Revenue recognized"
                    }
                ],
                "status": "posted"
            }
        }


class AccountBalance(BaseModel):
    """Account balance at a point in time"""
    account_id: str
    account_number: str
    account_name: str
    account_type: AccountType
    debit_balance: Decimal = Decimal("0.00")
    credit_balance: Decimal = Decimal("0.00")
    net_balance: Decimal = Decimal("0.00")
    normal_balance: NormalBalance

    @field_validator('debit_balance', 'credit_balance', 'net_balance', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class TrialBalance(BaseModel):
    """
    Trial Balance Report

    Lists all accounts with debit/credit balances.
    Total debits must equal total credits.
    """
    as_of_date: date = Field(..., description="Report date")
    accounts: List[AccountBalance] = Field(..., description="Account balances")
    total_debits: Decimal = Field(Decimal("0.00"), description="Sum of all debit balances")
    total_credits: Decimal = Field(Decimal("0.00"), description="Sum of all credit balances")
    is_balanced: bool = Field(..., description="Whether debits = credits")
    difference: Decimal = Field(Decimal("0.00"), description="Difference if not balanced")

    @field_validator('total_debits', 'total_credits', 'difference', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class GeneralLedgerEntry(BaseModel):
    """Entry in the general ledger for a specific account"""
    entry_id: str
    entry_number: str
    entry_date: date
    description: str
    reference: Optional[str]
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    balance: Decimal = Decimal("0.00")

    @field_validator('debit', 'credit', 'balance', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class GeneralLedger(BaseModel):
    """General Ledger for a specific account"""
    account: Account
    entries: List[GeneralLedgerEntry]
    opening_balance: Decimal = Decimal("0.00")
    closing_balance: Decimal = Decimal("0.00")
    period_start: Optional[date] = None
    period_end: Optional[date] = None

    @field_validator('opening_balance', 'closing_balance', mode='before')
    @classmethod
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v

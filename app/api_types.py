# app/api_types.py
# Shared API types - Keep in sync with frontend lib/api/types.ts
# This file defines the contract between frontend and backend

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum

# ============================================================================
# ENUMS
# ============================================================================
class BillStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

class ReceiptStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    ERROR = "error"

class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"

class ReportType(str, Enum):
    PROFIT_LOSS = "profit_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    EXPENSE = "expense"
    TAX_SUMMARY = "tax_summary"

# ============================================================================
# USER & AUTH
# ============================================================================
class User(BaseModel):
    id: str
    clerk_id: str
    email: str
    name: Optional[str] = None
    created_at: datetime

# ============================================================================
# ORGANIZATIONS
# ============================================================================
class Organization(BaseModel):
    id: str
    name: str
    owner_id: str
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

class CreateOrganizationRequest(BaseModel):
    name: str
    settings: Optional[Dict[str, Any]] = None

# ============================================================================
# TRANSACTIONS
# ============================================================================
class Transaction(BaseModel):
    id: str
    date: str
    description: str
    amount: float
    category: Optional[str] = None
    merchant: Optional[str] = None
    account_id: Optional[str] = None

class ClassifiedTransaction(Transaction):
    category: str
    subcategory: Optional[str] = None
    confidence: float
    tax_deductible: bool
    business_purpose: Optional[str] = None
    flags: Optional[List[str]] = None

class ClassifyTransactionsRequest(BaseModel):
    transactions: List[Transaction]
    org_id: Optional[str] = None

class ClassifyTransactionsResponse(BaseModel):
    classified: List[ClassifiedTransaction]
    processing_time_ms: float

# ============================================================================
# VENDORS
# ============================================================================
class Vendor(BaseModel):
    id: str
    org_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_terms: Optional[str] = None
    created_at: datetime

class CreateVendorRequest(BaseModel):
    name: str
    org_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_terms: Optional[str] = None

# ============================================================================
# BILLS
# ============================================================================
class Bill(BaseModel):
    id: str
    org_id: str
    vendor_id: str
    vendor_name: Optional[str] = None
    bill_number: str
    amount: float
    due_date: str
    status: BillStatus = BillStatus.PENDING
    description: Optional[str] = None
    created_at: datetime

class CreateBillRequest(BaseModel):
    org_id: str
    vendor_id: str
    bill_number: str
    amount: float
    due_date: str
    description: Optional[str] = None

class BillPayment(BaseModel):
    id: str
    bill_id: str
    amount: float
    payment_date: str
    payment_method: str
    reference: Optional[str] = None

# ============================================================================
# CUSTOMERS
# ============================================================================
class Customer(BaseModel):
    id: str
    org_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime

class CreateCustomerRequest(BaseModel):
    name: str
    org_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

# ============================================================================
# INVOICES
# ============================================================================
class InvoiceLineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float

class Invoice(BaseModel):
    id: str
    org_id: str
    customer_id: str
    customer_name: Optional[str] = None
    invoice_number: str
    amount: float
    due_date: str
    status: InvoiceStatus = InvoiceStatus.DRAFT
    line_items: List[InvoiceLineItem] = Field(default_factory=list)
    created_at: datetime

class CreateInvoiceRequest(BaseModel):
    org_id: str
    customer_id: str
    invoice_number: str
    amount: float
    due_date: str
    line_items: List[InvoiceLineItem] = Field(default_factory=list)

# ============================================================================
# RECEIPTS
# ============================================================================
class Receipt(BaseModel):
    id: str
    org_id: str
    file_name: str
    file_url: str
    vendor_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    category: Optional[str] = None
    status: ReceiptStatus = ReceiptStatus.PENDING
    created_at: datetime

# ============================================================================
# REPORTS
# ============================================================================
class Report(BaseModel):
    id: str
    org_id: str
    type: ReportType
    name: str
    date_from: str
    date_to: str
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

# ============================================================================
# BOOKKEEPING
# ============================================================================
class Account(BaseModel):
    id: str
    org_id: str
    code: str
    name: str
    type: AccountType
    parent_id: Optional[str] = None
    balance: float = 0.0

class JournalEntryLine(BaseModel):
    account_id: str
    account_name: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0

class JournalEntry(BaseModel):
    id: str
    org_id: str
    date: str
    description: str
    entries: List[JournalEntryLine]
    created_at: datetime

class CreateJournalEntryRequest(BaseModel):
    org_id: str
    date: str
    description: str
    entries: List[JournalEntryLine]

# ============================================================================
# PLAID
# ============================================================================
class PlaidLinkTokenResponse(BaseModel):
    link_token: str
    expiration: str

class PlaidExchangeRequest(BaseModel):
    public_token: str

class PlaidAccount(BaseModel):
    id: str
    name: str
    type: str
    subtype: str
    mask: str
    balance_current: float
    balance_available: Optional[float] = None

# ============================================================================
# CONTACT & SUPPORT
# ============================================================================
class ContactRequest(BaseModel):
    name: str
    email: str
    subject: Optional[str] = None
    message: str

class SupportTicket(BaseModel):
    id: str
    ticket_number: str
    email: str
    subject: str
    message: str
    status: TicketStatus = TicketStatus.OPEN
    created_at: datetime

# ============================================================================
# API RESPONSES
# ============================================================================
class ApiError(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

class ApiResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[ApiError] = None

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    has_more: bool

# ============================================================================
# ERROR CODES - Keep in sync with frontend
# ============================================================================
class ErrorCodes:
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

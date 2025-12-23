# app/invoicing/models.py

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator
import uuid


# ============================================================================
# ENUMS
# ============================================================================

class InvoiceStatus(str, Enum):
    """Invoice status"""
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    PARTIAL = "partial"  # Partially paid


class PaymentMethod(str, Enum):
    """Payment methods"""
    CASH = "cash"
    CHECK = "check"
    CREDIT_CARD = "credit_card"
    BANK_TRANSFER = "bank_transfer"
    ACH = "ach"
    WIRE = "wire"
    PAYPAL = "paypal"
    STRIPE = "stripe"
    OTHER = "other"


# ============================================================================
# CUSTOMER MODELS
# ============================================================================

class CustomerBase(BaseModel):
    """Base customer fields"""
    name: str = Field(..., min_length=1, max_length=255, description="Customer name")
    email: Optional[str] = Field(None, max_length=255, description="Customer email")
    phone: Optional[str] = Field(None, max_length=50, description="Customer phone")
    billing_address: Optional[str] = Field(None, description="Billing address")
    shipping_address: Optional[str] = Field(None, description="Shipping address")
    payment_terms: int = Field(30, description="Payment terms in days (e.g., Net 30)")
    tax_rate: Decimal = Field(Decimal("0.00"), description="Default tax rate (0.00-1.00)")
    notes: Optional[str] = Field(None, description="Internal notes")


class CustomerCreate(CustomerBase):
    """Create customer request"""
    pass


class CustomerUpdate(BaseModel):
    """Update customer request - all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    payment_terms: Optional[int] = None
    tax_rate: Optional[Decimal] = None
    notes: Optional[str] = None


class Customer(CustomerBase):
    """Customer record"""
    customer_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Computed fields
    total_billed: Decimal = Decimal("0.00")
    total_paid: Decimal = Decimal("0.00")
    balance_due: Decimal = Decimal("0.00")

    class Config:
        from_attributes = True


# ============================================================================
# INVOICE ITEM MODELS
# ============================================================================

class InvoiceItemBase(BaseModel):
    """Base invoice item fields"""
    description: str = Field(..., min_length=1, description="Item description")
    quantity: Decimal = Field(Decimal("1.00"), gt=0, description="Quantity")
    rate: Decimal = Field(..., ge=0, description="Unit rate/price")

    @property
    def amount(self) -> Decimal:
        """Calculate line item amount"""
        return self.quantity * self.rate


class InvoiceItemCreate(InvoiceItemBase):
    """Create invoice item request"""
    pass


class InvoiceItem(InvoiceItemBase):
    """Invoice item record"""
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    invoice_id: str
    amount: Decimal = Field(default=Decimal("0.00"))
    line_order: int = 0

    @field_validator('amount', mode='before')
    @classmethod
    def calculate_amount(cls, v, info):
        """Auto-calculate amount from quantity * rate"""
        if 'quantity' in info.data and 'rate' in info.data:
            return info.data['quantity'] * info.data['rate']
        return v

    class Config:
        from_attributes = True


# ============================================================================
# INVOICE MODELS
# ============================================================================

class InvoiceBase(BaseModel):
    """Base invoice fields"""
    customer_id: str
    invoice_date: date = Field(default_factory=date.today)
    due_date: date
    notes: Optional[str] = None
    terms: Optional[str] = Field(None, description="Payment terms text")
    tax_rate: Decimal = Field(Decimal("0.00"), ge=0, le=1, description="Tax rate (0.00-1.00)")
    discount_amount: Decimal = Field(Decimal("0.00"), ge=0, description="Discount amount")


class InvoiceCreate(InvoiceBase):
    """Create invoice request"""
    items: List[InvoiceItemCreate] = Field(..., min_length=1, description="Invoice line items")


class InvoiceUpdate(BaseModel):
    """Update invoice request - all fields optional"""
    customer_id: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[InvoiceStatus] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    tax_rate: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    items: Optional[List[InvoiceItemCreate]] = None


class Invoice(InvoiceBase):
    """Invoice record"""
    invoice_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    invoice_number: str  # INV-0001, INV-0002, etc.
    status: InvoiceStatus = InvoiceStatus.DRAFT

    # Amounts
    subtotal: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    amount_paid: Decimal = Decimal("0.00")
    balance_due: Decimal = Decimal("0.00")

    # Items
    items: List[InvoiceItem] = []

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    sent_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    # Computed
    days_overdue: int = 0

    @model_validator(mode='after')
    def calculate_totals(self):
        """Calculate invoice totals"""
        # Calculate subtotal from items
        self.subtotal = sum(item.amount for item in self.items)

        # Apply discount
        subtotal_after_discount = self.subtotal - self.discount_amount

        # Calculate tax
        self.tax_amount = subtotal_after_discount * self.tax_rate

        # Calculate total
        self.total = subtotal_after_discount + self.tax_amount

        # Calculate balance due
        self.balance_due = self.total - self.amount_paid

        # Calculate days overdue
        if self.status in [InvoiceStatus.SENT, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE]:
            days_diff = (date.today() - self.due_date).days
            self.days_overdue = max(0, days_diff)

            # Auto-update status if overdue
            if self.days_overdue > 0 and self.balance_due > 0:
                self.status = InvoiceStatus.OVERDUE

        return self

    class Config:
        from_attributes = True


# ============================================================================
# PAYMENT MODELS
# ============================================================================

class PaymentBase(BaseModel):
    """Base payment fields"""
    invoice_id: str
    amount: Decimal = Field(..., gt=0, description="Payment amount")
    payment_date: date = Field(default_factory=date.today)
    payment_method: PaymentMethod = PaymentMethod.OTHER
    reference: Optional[str] = Field(None, description="Check number, transaction ID, etc.")
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    """Create payment request"""
    pass


class Payment(PaymentBase):
    """Payment record"""
    payment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    customer_id: str  # Denormalized for easy queries
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True


# ============================================================================
# REPORTS
# ============================================================================

class ARAgingBucket(BaseModel):
    """AR aging bucket (e.g., 0-30 days, 31-60 days, etc.)"""
    bucket_name: str  # "Current", "1-30 days", "31-60 days", "61-90 days", "90+ days"
    invoice_count: int = 0
    total_amount: Decimal = Decimal("0.00")
    invoices: List[Invoice] = []


class ARAgingReport(BaseModel):
    """Accounts Receivable Aging Report"""
    report_date: date = Field(default_factory=date.today)
    organization_id: str

    # Summary totals
    total_outstanding: Decimal = Decimal("0.00")
    total_current: Decimal = Decimal("0.00")
    total_1_30: Decimal = Decimal("0.00")
    total_31_60: Decimal = Decimal("0.00")
    total_61_90: Decimal = Decimal("0.00")
    total_90_plus: Decimal = Decimal("0.00")

    # Buckets
    buckets: List[ARAgingBucket] = []

    # Customer breakdown
    customers: List[Dict] = []  # Customer name + aging buckets


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_invoice_totals(invoice: Invoice) -> bool:
    """Validate invoice totals are calculated correctly"""
    expected_subtotal = sum(item.amount for item in invoice.items)
    expected_tax = (expected_subtotal - invoice.discount_amount) * invoice.tax_rate
    expected_total = expected_subtotal - invoice.discount_amount + expected_tax

    return (
        abs(invoice.subtotal - expected_subtotal) < Decimal("0.01") and
        abs(invoice.tax_amount - expected_tax) < Decimal("0.01") and
        abs(invoice.total - expected_total) < Decimal("0.01")
    )

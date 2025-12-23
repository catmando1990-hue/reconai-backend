# app/bills/models.py

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

class BillStatus(str, Enum):
    """Bill status"""
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class PaymentMethod(str, Enum):
    """Payment methods"""
    CASH = "cash"
    CHECK = "check"
    CREDIT_CARD = "credit_card"
    BANK_TRANSFER = "bank_transfer"
    ACH = "ach"
    WIRE = "wire"
    PAYPAL = "paypal"
    OTHER = "other"


# ============================================================================
# VENDOR MODELS
# ============================================================================

class VendorBase(BaseModel):
    """Base vendor fields"""
    name: str = Field(..., min_length=1, max_length=255, description="Vendor name")
    email: Optional[str] = Field(None, max_length=255, description="Vendor email")
    phone: Optional[str] = Field(None, max_length=50, description="Vendor phone")
    address: Optional[str] = Field(None, description="Vendor address")
    payment_terms: int = Field(30, description="Payment terms in days (e.g., Net 30)")
    ein: Optional[str] = Field(None, max_length=20, description="EIN for 1099 tracking")
    requires_1099: bool = Field(False, description="Whether vendor requires 1099")
    notes: Optional[str] = Field(None, description="Internal notes")


class VendorCreate(VendorBase):
    """Create vendor request"""
    pass


class VendorUpdate(BaseModel):
    """Update vendor request - all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    payment_terms: Optional[int] = None
    ein: Optional[str] = Field(None, max_length=20)
    requires_1099: Optional[bool] = None
    notes: Optional[str] = None


class Vendor(VendorBase):
    """Vendor record"""
    vendor_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Computed fields
    total_billed: Decimal = Decimal("0.00")
    total_paid: Decimal = Decimal("0.00")
    balance_due: Decimal = Decimal("0.00")
    ytd_payments: Decimal = Decimal("0.00")  # For 1099 tracking

    class Config:
        from_attributes = True


# ============================================================================
# BILL ITEM MODELS
# ============================================================================

class BillItemBase(BaseModel):
    """Base bill item fields"""
    description: str = Field(..., min_length=1, description="Item description")
    category: Optional[str] = Field(None, description="Expense category")
    account_id: Optional[str] = Field(None, description="Chart of accounts mapping")
    amount: Decimal = Field(..., gt=0, description="Line item amount")


class BillItemCreate(BillItemBase):
    """Create bill item request"""
    pass


class BillItem(BillItemBase):
    """Bill item record"""
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bill_id: str
    line_order: int = 0

    class Config:
        from_attributes = True


# ============================================================================
# BILL MODELS
# ============================================================================

class BillBase(BaseModel):
    """Base bill fields"""
    vendor_id: str
    bill_number: Optional[str] = Field(None, description="Vendor's bill/invoice number")
    bill_date: date = Field(default_factory=date.today)
    due_date: date
    notes: Optional[str] = None


class BillCreate(BillBase):
    """Create bill request"""
    items: List[BillItemCreate] = Field(..., min_length=1, description="Bill line items")


class BillUpdate(BaseModel):
    """Update bill request - all fields optional"""
    vendor_id: Optional[str] = None
    bill_number: Optional[str] = None
    bill_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[BillStatus] = None
    notes: Optional[str] = None
    items: Optional[List[BillItemCreate]] = None


class Bill(BillBase):
    """Bill record"""
    bill_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    status: BillStatus = BillStatus.PENDING

    # Amounts
    total: Decimal = Decimal("0.00")
    amount_paid: Decimal = Decimal("0.00")
    balance_due: Decimal = Decimal("0.00")

    # Items
    items: List[BillItem] = []

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    paid_at: Optional[datetime] = None

    # Computed
    days_overdue: int = 0

    @model_validator(mode='after')
    def calculate_totals(self):
        """Calculate bill totals"""
        # Calculate total from items
        self.total = sum(item.amount for item in self.items)

        # Calculate balance due
        self.balance_due = self.total - self.amount_paid

        # Calculate days overdue
        if self.status in [BillStatus.PENDING, BillStatus.PARTIAL, BillStatus.OVERDUE]:
            days_diff = (date.today() - self.due_date).days
            self.days_overdue = max(0, days_diff)

            # Auto-update status if overdue
            if self.days_overdue > 0 and self.balance_due > 0:
                self.status = BillStatus.OVERDUE

        return self

    class Config:
        from_attributes = True


# ============================================================================
# BILL PAYMENT MODELS
# ============================================================================

class BillPaymentBase(BaseModel):
    """Base bill payment fields"""
    bill_id: str
    amount: Decimal = Field(..., gt=0, description="Payment amount")
    payment_date: date = Field(default_factory=date.today)
    payment_method: PaymentMethod = PaymentMethod.CHECK
    reference: Optional[str] = Field(None, description="Check number, transaction ID, etc.")
    notes: Optional[str] = None


class BillPaymentCreate(BillPaymentBase):
    """Create bill payment request"""
    pass


class BillPayment(BillPaymentBase):
    """Bill payment record"""
    payment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    vendor_id: str  # Denormalized for easy queries
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True


# ============================================================================
# REPORTS
# ============================================================================

class APAgingBucket(BaseModel):
    """AP aging bucket"""
    bucket_name: str  # "Current", "1-30 days", etc.
    bill_count: int = 0
    total_amount: Decimal = Decimal("0.00")
    bills: List[Bill] = []


class APAgingReport(BaseModel):
    """Accounts Payable Aging Report"""
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
    buckets: List[APAgingBucket] = []

    # Vendor breakdown
    vendors: List[dict] = []


class Vendor1099Report(BaseModel):
    """1099 Report for a vendor"""
    vendor_id: str
    vendor_name: str
    vendor_ein: Optional[str]
    tax_year: int
    total_payments: Decimal
    requires_1099: bool
    needs_filing: bool  # True if >= $600 threshold
    payment_breakdown: List[dict] = []  # Monthly breakdown


class Organization1099Summary(BaseModel):
    """1099 Summary for entire organization"""
    organization_id: str
    tax_year: int
    total_vendors: int
    vendors_requiring_1099: int
    total_1099_payments: Decimal
    vendors: List[Vendor1099Report] = []

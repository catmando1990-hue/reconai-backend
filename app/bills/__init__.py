# app/bills/__init__.py
"""
ReconAI Bills & Accounts Payable Module

Provides:
- Vendor management
- Bill tracking and payment
- AP aging reports
- 1099 preparation
- Automatic journal entry creation
"""

from .models import (
    Vendor,
    VendorCreate,
    VendorUpdate,
    Bill,
    BillCreate,
    BillUpdate,
    BillStatus,
    BillItem,
    BillItemCreate,
    BillPayment,
    BillPaymentCreate,
    PaymentMethod,
    APAgingReport,
    APAgingBucket,
    Vendor1099Report,
    Organization1099Summary
)

from .engine import BillsEngine

__all__ = [
    "Vendor",
    "VendorCreate",
    "VendorUpdate",
    "Bill",
    "BillCreate",
    "BillUpdate",
    "BillStatus",
    "BillItem",
    "BillItemCreate",
    "BillPayment",
    "BillPaymentCreate",
    "PaymentMethod",
    "APAgingReport",
    "APAgingBucket",
    "Vendor1099Report",
    "Organization1099Summary",
    "BillsEngine"
]

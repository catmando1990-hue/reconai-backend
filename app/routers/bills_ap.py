# app/routers/bills_ap.py

from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from datetime import date

from app.bills import (
    Vendor,
    VendorCreate,
    VendorUpdate,
    Bill,
    BillCreate,
    BillUpdate,
    BillStatus,
    BillPayment,
    BillPaymentCreate,
    APAgingReport,
    Organization1099Summary
)

try:
    from .auth import get_current_user_id, get_current_organization_id
except ImportError:
    def get_current_user_id():
        return "system"
    def get_current_organization_id():
        return "default-org"

router = APIRouter(prefix="/api/bills", tags=["bills"])

_bills_engine = None

def get_bills_engine():
    if _bills_engine is None:
        raise HTTPException(status_code=500, detail="Bills engine not initialized")
    return _bills_engine

def set_bills_engine(engine):
    global _bills_engine
    _bills_engine = engine

# ============================================================================
# VENDOR ENDPOINTS
# ============================================================================

@router.post("/vendors", response_model=Vendor, status_code=201)
async def create_vendor(data: VendorCreate, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().create_vendor(data, org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors", response_model=List[Vendor])
async def list_vendors(active_only: bool = True, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().list_vendors(org_id, active_only=active_only)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors/{vendor_id}", response_model=Vendor)
async def get_vendor(vendor_id: str):
    try:
        vendor = get_bills_engine().get_vendor(vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        return vendor
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/vendors/{vendor_id}", response_model=Vendor)
async def update_vendor(vendor_id: str, updates: VendorUpdate):
    try:
        vendor = get_bills_engine().update_vendor(vendor_id, updates)
        if not vendor:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        return vendor
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/vendors/{vendor_id}", status_code=204)
async def delete_vendor(vendor_id: str):
    try:
        deleted = get_bills_engine().delete_vendor(vendor_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# BILL ENDPOINTS
# ============================================================================

@router.post("/", response_model=Bill, status_code=201)
async def create_bill(data: BillCreate, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().create_bill(data, org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[Bill])
async def list_bills(
    vendor_id: Optional[str] = None,
    status_filter: Optional[BillStatus] = None,
    overdue_only: bool = False,
    org_id: str = Depends(get_current_organization_id)
):
    try:
        return get_bills_engine().list_bills(org_id, vendor_id=vendor_id, status=status_filter, overdue_only=overdue_only)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{bill_id}", response_model=Bill)
async def get_bill(bill_id: str):
    try:
        bill = get_bills_engine().get_bill(bill_id)
        if not bill:
            raise HTTPException(status_code=404, detail=f"Bill {bill_id} not found")
        return bill
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PAYMENT ENDPOINTS
# ============================================================================

@router.post("/payments", response_model=BillPayment, status_code=201)
async def record_payment(data: BillPaymentCreate, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().record_payment(data, org_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payments", response_model=List[BillPayment])
async def list_payments(bill_id: Optional[str] = None, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().list_payments(org_id, bill_id=bill_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payments/{payment_id}", response_model=BillPayment)
async def get_payment(payment_id: str):
    try:
        payment = get_bills_engine().get_payment(payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
        return payment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# REPORTS
# ============================================================================

@router.get("/reports/ap-aging", response_model=APAgingReport)
async def get_ap_aging_report(as_of_date: Optional[date] = None, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().generate_ap_aging_report(org_id, as_of_date=as_of_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/1099/{tax_year}", response_model=Organization1099Summary)
async def get_1099_report(tax_year: int, org_id: str = Depends(get_current_organization_id)):
    try:
        return get_bills_engine().generate_1099_report(org_id, tax_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    engine = get_bills_engine()
    return {"status": "healthy", "service": "bills", "engine_initialized": engine is not None}

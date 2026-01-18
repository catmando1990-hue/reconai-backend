# app/routers/invoicing.py
# Phase-1 Hotfix: DEPRECATION NOTICE
# This router (/api/invoicing) is scheduled for deprecation.
# New integrations should use /api/invoices as the canonical invoice API.
# Existing functionality preserved for backward compatibility.

from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from datetime import date

from app.invoicing import (
    Customer,
    CustomerCreate,
    CustomerUpdate,
    Invoice,
    InvoiceCreate,
    InvoiceUpdate,
    InvoiceStatus,
    Payment,
    PaymentCreate,
    ARAgingReport
)

from app.auth_context import get_current_organization_id, get_current_user_id


router = APIRouter(prefix="/api/invoicing", tags=["invoicing"])

# Engine will be injected by main.py
_invoicing_engine = None


def get_invoicing_engine():
    """Get invoicing engine instance"""
    if _invoicing_engine is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invoicing engine not initialized"
        )
    return _invoicing_engine


def set_invoicing_engine(engine):
    """Set global invoicing engine instance"""
    global _invoicing_engine
    _invoicing_engine = engine


# ============================================================================
# CUSTOMER ENDPOINTS
# ============================================================================

@router.post("/customers", response_model=Customer, status_code=status.HTTP_201_CREATED)
async def create_customer(
    customer_data: CustomerCreate,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Create a new customer"""
    try:
        engine = get_invoicing_engine()
        customer = engine.create_customer(customer_data, organization_id)
        return customer
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating customer: {str(e)}"
        )


@router.get("/customers", response_model=List[Customer])
async def list_customers(
    active_only: bool = True,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """List all customers for the organization"""
    try:
        engine = get_invoicing_engine()
        customers = engine.list_customers(organization_id, active_only=active_only)
        return customers
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing customers: {str(e)}"
        )


@router.get("/customers/{customer_id}", response_model=Customer)
async def get_customer(
    customer_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Get a specific customer by ID"""
    try:
        engine = get_invoicing_engine()
        customer = engine.get_customer(customer_id)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer {customer_id} not found"
            )
        return customer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching customer: {str(e)}"
        )


@router.patch("/customers/{customer_id}", response_model=Customer)
async def update_customer(
    customer_id: str,
    updates: CustomerUpdate,
    current_user_id: str = Depends(get_current_user_id)
):
    """Update a customer"""
    try:
        engine = get_invoicing_engine()
        customer = engine.update_customer(customer_id, updates)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer {customer_id} not found"
            )
        return customer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating customer: {str(e)}"
        )


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Soft delete a customer"""
    try:
        engine = get_invoicing_engine()
        deleted = engine.delete_customer(customer_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer {customer_id} not found"
            )
        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting customer: {str(e)}"
        )


# ============================================================================
# INVOICE ENDPOINTS
# ============================================================================

@router.post("/invoices", response_model=Invoice, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    invoice_data: InvoiceCreate,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Create a new invoice"""
    try:
        engine = get_invoicing_engine()
        invoice = engine.create_invoice(invoice_data, organization_id)
        return invoice
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating invoice: {str(e)}"
        )


@router.get("/invoices", response_model=List[Invoice])
async def list_invoices(
    customer_id: Optional[str] = None,
    status_filter: Optional[InvoiceStatus] = None,
    overdue_only: bool = False,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """List invoices with optional filters"""
    try:
        engine = get_invoicing_engine()
        invoices = engine.list_invoices(
            organization_id,
            customer_id=customer_id,
            status=status_filter,
            overdue_only=overdue_only
        )
        return invoices
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing invoices: {str(e)}"
        )


@router.get("/invoices/{invoice_id}", response_model=Invoice)
async def get_invoice(
    invoice_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Get a specific invoice by ID"""
    try:
        engine = get_invoicing_engine()
        invoice = engine.get_invoice(invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {invoice_id} not found"
            )
        return invoice
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching invoice: {str(e)}"
        )


@router.post("/invoices/{invoice_id}/send", response_model=Invoice)
async def send_invoice(
    invoice_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Mark invoice as sent and create journal entry"""
    try:
        engine = get_invoicing_engine()
        invoice = engine.send_invoice(invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {invoice_id} not found"
            )
        return invoice
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending invoice: {str(e)}"
        )


@router.post("/invoices/{invoice_id}/cancel", response_model=Invoice)
async def cancel_invoice(
    invoice_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Cancel an invoice"""
    try:
        engine = get_invoicing_engine()
        invoice = engine.cancel_invoice(invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {invoice_id} not found"
            )
        return invoice
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling invoice: {str(e)}"
        )


# ============================================================================
# PAYMENT ENDPOINTS
# ============================================================================

@router.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payment_data: PaymentCreate,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Record a payment against an invoice"""
    try:
        engine = get_invoicing_engine()
        payment = engine.record_payment(payment_data, organization_id)
        return payment
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error recording payment: {str(e)}"
        )


@router.get("/payments", response_model=List[Payment])
async def list_payments(
    invoice_id: Optional[str] = None,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """List payments, optionally filtered by invoice"""
    try:
        engine = get_invoicing_engine()
        payments = engine.list_payments(organization_id, invoice_id=invoice_id)
        return payments
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing payments: {str(e)}"
        )


@router.get("/payments/{payment_id}", response_model=Payment)
async def get_payment(
    payment_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Get a specific payment by ID"""
    try:
        engine = get_invoicing_engine()
        payment = engine.get_payment(payment_id)
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found"
            )
        return payment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching payment: {str(e)}"
        )


# ============================================================================
# REPORTS
# ============================================================================

@router.get("/reports/ar-aging", response_model=ARAgingReport)
async def get_ar_aging_report(
    as_of_date: Optional[date] = None,
    organization_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Generate Accounts Receivable Aging Report"""
    try:
        engine = get_invoicing_engine()
        report = engine.generate_ar_aging_report(organization_id, as_of_date=as_of_date)
        return report
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating AR aging report: {str(e)}"
        )


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    engine = get_invoicing_engine()
    return {
        "status": "healthy",
        "service": "invoicing",
        "engine_initialized": engine is not None
    }

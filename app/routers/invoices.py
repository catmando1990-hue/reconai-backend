# app/routers/invoices.py

"""
Invoicing API
Handles invoice creation, management, and payment tracking
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query, Request
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Literal
import sqlite3
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from ..db import DB_PATH
from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/invoices", tags=["Invoices"])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


# =========================================================================
# MODELS
# =========================================================================

class InvoiceLineItem(BaseModel):
    """Invoice line item"""
    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    amount: Optional[float] = None  # Calculated: quantity * unit_price
    tax_rate: float = Field(default=0.0, ge=0, le=1)
    tax_amount: Optional[float] = None  # Calculated
    account_code: Optional[str] = Field(None, max_length=20)

    @validator('amount', always=True)
    def calculate_amount(cls, v, values):
        if 'quantity' in values and 'unit_price' in values:
            return round(values['quantity'] * values['unit_price'], 2)
        return v

    @validator('tax_amount', always=True)
    def calculate_tax(cls, v, values):
        if 'amount' in values and 'tax_rate' in values and values['amount']:
            return round(values['amount'] * values['tax_rate'], 2)
        return v


class CreateInvoiceRequest(BaseModel):
    """Create invoice request"""
    customer_id: str
    entity_id: Optional[str] = None
    invoice_date: str  # ISO date
    due_date: str  # ISO date
    line_items: List[InvoiceLineItem] = Field(..., min_items=1)
    notes: Optional[str] = Field(None, max_length=2000)
    terms: Optional[str] = Field(None, max_length=500)
    discount_amount: float = Field(default=0.0, ge=0)
    shipping_amount: float = Field(default=0.0, ge=0)
    status: Literal["draft", "sent", "paid", "overdue", "cancelled"] = "draft"

    @validator('due_date')
    def validate_due_date(cls, v, values):
        if 'invoice_date' in values:
            invoice_date = datetime.fromisoformat(values['invoice_date'])
            due_date = datetime.fromisoformat(v)
            if due_date < invoice_date:
                raise ValueError('Due date cannot be before invoice date')
        return v


class UpdateInvoiceRequest(BaseModel):
    """Update invoice request"""
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    line_items: Optional[List[InvoiceLineItem]] = None
    notes: Optional[str] = Field(None, max_length=2000)
    terms: Optional[str] = Field(None, max_length=500)
    discount_amount: Optional[float] = Field(None, ge=0)
    shipping_amount: Optional[float] = Field(None, ge=0)
    status: Optional[Literal["draft", "sent", "paid", "overdue", "cancelled"]] = None


class InvoiceLineItemResponse(BaseModel):
    """Invoice line item response"""
    id: str
    description: str
    quantity: float
    unit_price: float
    amount: float
    tax_rate: float
    tax_amount: float
    account_code: Optional[str]


class InvoiceResponse(BaseModel):
    """Invoice response"""
    id: str
    organization_id: str
    entity_id: Optional[str]
    customer_id: str
    customer_name: str
    invoice_number: str
    invoice_date: str
    due_date: str
    subtotal: float
    tax_total: float
    discount_amount: float
    shipping_amount: float
    total_amount: float
    amount_paid: float
    amount_due: float
    status: str
    notes: Optional[str]
    terms: Optional[str]
    line_items: List[InvoiceLineItemResponse]
    created_at: str
    updated_at: str
    sent_at: Optional[str]
    paid_at: Optional[str]


class RecordPaymentRequest(BaseModel):
    """Record payment for invoice"""
    amount: float = Field(..., gt=0)
    payment_date: str  # ISO date
    payment_method: Literal["cash", "check", "credit_card", "bank_transfer", "other"]
    reference_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


class PaymentResponse(BaseModel):
    """Payment response"""
    id: str
    invoice_id: str
    amount: float
    payment_date: str
    payment_method: str
    reference_number: Optional[str]
    notes: Optional[str]
    created_at: str


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def generate_invoice_number(org_id: str) -> str:
    """Generate next invoice number for organization"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT invoice_number FROM invoices
            WHERE organization_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (org_id,))

        last_invoice = cursor.fetchone()

        if last_invoice:
            # Extract number from format INV-00001
            last_num = int(last_invoice[0].split('-')[1])
            next_num = last_num + 1
        else:
            next_num = 1

        return f"INV-{next_num:05d}"


def calculate_invoice_totals(line_items: List[InvoiceLineItem], discount: float = 0.0, shipping: float = 0.0):
    """Calculate invoice totals"""
    subtotal = sum(item.amount or 0 for item in line_items)
    tax_total = sum(item.tax_amount or 0 for item in line_items)
    total = subtotal + tax_total - discount + shipping

    return {
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "total_amount": round(total, 2)
    }


def get_invoice_with_items(invoice_id: str, org_id: str) -> Optional[InvoiceResponse]:
    """Get invoice with line items"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Get invoice
        cursor = conn.execute("""
            SELECT i.*, c.name as customer_name
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.id = ? AND i.organization_id = ?
        """, (invoice_id, org_id))

        invoice_row = cursor.fetchone()
        if not invoice_row:
            return None

        # Get line items
        cursor = conn.execute("""
            SELECT * FROM invoice_items
            WHERE invoice_id = ?
            ORDER BY id ASC
        """, (invoice_id,))

        line_items = [
            InvoiceLineItemResponse(
                id=row["id"],
                description=row["description"],
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                amount=row["amount"],
                tax_rate=row["tax_rate"],
                tax_amount=row["tax_amount"],
                account_code=row["account_code"]
            )
            for row in cursor.fetchall()
        ]

        return InvoiceResponse(
            id=invoice_row["id"],
            organization_id=invoice_row["organization_id"],
            entity_id=invoice_row["entity_id"],
            customer_id=invoice_row["customer_id"],
            customer_name=invoice_row["customer_name"],
            invoice_number=invoice_row["invoice_number"],
            invoice_date=invoice_row["invoice_date"],
            due_date=invoice_row["due_date"],
            subtotal=invoice_row["subtotal"],
            tax_total=invoice_row["tax_total"],
            discount_amount=invoice_row["discount_amount"],
            shipping_amount=invoice_row["shipping_amount"],
            total_amount=invoice_row["total_amount"],
            amount_paid=invoice_row["amount_paid"],
            amount_due=invoice_row["amount_due"],
            status=invoice_row["status"],
            notes=invoice_row["notes"],
            terms=invoice_row["terms"],
            line_items=line_items,
            created_at=invoice_row["created_at"],
            updated_at=invoice_row["updated_at"],
            sent_at=invoice_row["sent_at"],
            paid_at=invoice_row["paid_at"]
        )


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    request: CreateInvoiceRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Create new invoice

    Requires: create_transactions permission (or higher)
    """
    try:
        # Verify customer exists and belongs to organization
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT id FROM customers
                WHERE id = ? AND organization_id = ? AND is_active = 1
            """, (request.customer_id, org_id))

            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found or inactive"
                )

            # Generate invoice ID and number
            invoice_id = f"invoice-{uuid.uuid4().hex[:12]}"
            invoice_number = generate_invoice_number(org_id)

            # Calculate totals
            totals = calculate_invoice_totals(
                request.line_items,
                request.discount_amount,
                request.shipping_amount
            )

            # Create invoice
            conn.execute("""
                INSERT INTO invoices (
                    id, organization_id, entity_id, customer_id,
                    invoice_number, invoice_date, due_date,
                    subtotal, tax_total, discount_amount, shipping_amount,
                    total_amount, amount_paid, amount_due,
                    status, notes, terms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice_id, org_id, request.entity_id, request.customer_id,
                invoice_number, request.invoice_date, request.due_date,
                totals["subtotal"], totals["tax_total"], request.discount_amount, request.shipping_amount,
                totals["total_amount"], 0.0, totals["total_amount"],
                request.status, request.notes, request.terms
            ))

            # Create line items
            for item in request.line_items:
                line_item_id = f"lineitem-{uuid.uuid4().hex[:12]}"
                conn.execute("""
                    INSERT INTO invoice_items (
                        id, invoice_id, description, quantity, unit_price,
                        amount, tax_rate, tax_amount, account_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    line_item_id, invoice_id, item.description, item.quantity, item.unit_price,
                    item.amount, item.tax_rate, item.tax_amount, item.account_code
                ))

            # Update sent_at if status is sent
            if request.status == "sent":
                conn.execute("""
                    UPDATE invoices SET sent_at = datetime('now')
                    WHERE id = ?
                """, (invoice_id,))

            conn.commit()

        # Return created invoice
        return get_invoice_with_items(invoice_id, org_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invoice: {str(e)}"
        )


@router.get("/", response_model=dict)
async def list_invoices(
    request: Request,
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    invoice_status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    List invoices for organization

    Filter by entity_id, customer_id, status, or date range
    P0 FIX: Returns request_id on all responses.
    """
    request_id = _get_request_id(request)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            query = """
                SELECT i.*, c.name as customer_name
                FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.organization_id = ?
            """
            params = [org_id]

            if entity_id:
                query += " AND i.entity_id = ?"
                params.append(entity_id)

            if customer_id:
                query += " AND i.customer_id = ?"
                params.append(customer_id)

            if invoice_status:
                query += " AND i.status = ?"
                params.append(invoice_status)

            if start_date:
                query += " AND i.invoice_date >= ?"
                params.append(start_date)

            if end_date:
                query += " AND i.invoice_date <= ?"
                params.append(end_date)

            query += " ORDER BY i.invoice_date DESC, i.created_at DESC"

            cursor = conn.execute(query, params)
            invoice_rows = cursor.fetchall()

            # Get line items for each invoice
            invoices = []
            for invoice_row in invoice_rows:
                cursor = conn.execute("""
                    SELECT * FROM invoice_items
                    WHERE invoice_id = ?
                    ORDER BY id ASC
                """, (invoice_row["id"],))

                line_items = [
                    InvoiceLineItemResponse(
                        id=row["id"],
                        description=row["description"],
                        quantity=row["quantity"],
                        unit_price=row["unit_price"],
                        amount=row["amount"],
                        tax_rate=row["tax_rate"],
                        tax_amount=row["tax_amount"],
                        account_code=row["account_code"]
                    )
                    for row in cursor.fetchall()
                ]

                invoices.append(InvoiceResponse(
                    id=invoice_row["id"],
                    organization_id=invoice_row["organization_id"],
                    entity_id=invoice_row["entity_id"],
                    customer_id=invoice_row["customer_id"],
                    customer_name=invoice_row["customer_name"],
                    invoice_number=invoice_row["invoice_number"],
                    invoice_date=invoice_row["invoice_date"],
                    due_date=invoice_row["due_date"],
                    subtotal=invoice_row["subtotal"],
                    tax_total=invoice_row["tax_total"],
                    discount_amount=invoice_row["discount_amount"],
                    shipping_amount=invoice_row["shipping_amount"],
                    total_amount=invoice_row["total_amount"],
                    amount_paid=invoice_row["amount_paid"],
                    amount_due=invoice_row["amount_due"],
                    status=invoice_row["status"],
                    notes=invoice_row["notes"],
                    terms=invoice_row["terms"],
                    line_items=line_items,
                    created_at=invoice_row["created_at"],
                    updated_at=invoice_row["updated_at"],
                    sent_at=invoice_row["sent_at"],
                    paid_at=invoice_row["paid_at"]
                ).dict())

            return {"items": invoices, "request_id": request_id}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "invoices_list_failed", "message": str(e), "request_id": request_id}
        )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Get invoice by ID"""
    invoice = get_invoice_with_items(invoice_id, org_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    return invoice


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: str,
    request: UpdateInvoiceRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Update invoice

    Cannot update paid invoices
    Requires: edit_transactions permission (or higher)
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Check if invoice exists and is not paid
            cursor = conn.execute("""
                SELECT status FROM invoices
                WHERE id = ? AND organization_id = ?
            """, (invoice_id, org_id))

            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found"
                )

            if row[0] == "paid":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot update paid invoice"
                )

            # Update line items if provided
            if request.line_items is not None:
                # Delete existing line items
                conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))

                # Insert new line items
                for item in request.line_items:
                    line_item_id = f"lineitem-{uuid.uuid4().hex[:12]}"
                    conn.execute("""
                        INSERT INTO invoice_items (
                            id, invoice_id, description, quantity, unit_price,
                            amount, tax_rate, tax_amount, account_code
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        line_item_id, invoice_id, item.description, item.quantity, item.unit_price,
                        item.amount, item.tax_amount, item.tax_amount, item.account_code
                    ))

                # Recalculate totals
                discount = request.discount_amount if request.discount_amount is not None else 0
                shipping = request.shipping_amount if request.shipping_amount is not None else 0
                totals = calculate_invoice_totals(request.line_items, discount, shipping)

                conn.execute("""
                    UPDATE invoices
                    SET subtotal = ?, tax_total = ?, total_amount = ?, amount_due = ?
                    WHERE id = ?
                """, (
                    totals["subtotal"], totals["tax_total"],
                    totals["total_amount"], totals["total_amount"],
                    invoice_id
                ))

            # P0 Security: Column allowlist to prevent SQL injection
            allowed_fields = {
                'invoice_date', 'due_date', 'notes', 'terms',
                'discount_amount', 'shipping_amount', 'status'
            }

            # Update other fields
            updates = request.model_dump(exclude_none=True, exclude={"line_items"})
            # Filter to allowed fields only
            updates = {k: v for k, v in updates.items() if k in allowed_fields}

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                set_clause += ", updated_at = datetime('now')"
                values = list(updates.values()) + [invoice_id, org_id]

                # Update sent_at if status changed to sent
                if updates.get("status") == "sent":
                    conn.execute("""
                        UPDATE invoices SET sent_at = datetime('now')
                        WHERE id = ? AND sent_at IS NULL
                    """, (invoice_id,))

                conn.execute(
                    f"UPDATE invoices SET {set_clause} WHERE id = ? AND organization_id = ?",
                    values
                )

            conn.commit()

        return get_invoice_with_items(invoice_id, org_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update invoice: {str(e)}"
        )


@router.post("/{invoice_id}/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    invoice_id: str,
    request: RecordPaymentRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Record payment for invoice

    Updates invoice amount_paid and status
    Updates customer outstanding_balance
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get invoice
            cursor = conn.execute("""
                SELECT customer_id, amount_due, status FROM invoices
                WHERE id = ? AND organization_id = ?
            """, (invoice_id, org_id))

            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found"
                )

            customer_id, amount_due, invoice_status = row

            if invoice_status == "cancelled":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot record payment for cancelled invoice"
                )

            if request.amount > amount_due:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payment amount ${request.amount} exceeds amount due ${amount_due}"
                )

            # Create payment record
            payment_id = f"payment-{uuid.uuid4().hex[:12]}"
            conn.execute("""
                INSERT INTO payments (
                    id, invoice_id, amount, payment_date,
                    payment_method, reference_number, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                payment_id, invoice_id, request.amount, request.payment_date,
                request.payment_method, request.reference_number, request.notes
            ))

            # Update invoice
            new_amount_paid = cursor.execute(
                "SELECT amount_paid FROM invoices WHERE id = ?",
                (invoice_id,)
            ).fetchone()[0] + request.amount

            new_amount_due = amount_due - request.amount
            new_status = "paid" if new_amount_due == 0 else invoice_status

            conn.execute("""
                UPDATE invoices
                SET amount_paid = ?, amount_due = ?, status = ?,
                    paid_at = CASE WHEN ? = 0 THEN datetime('now') ELSE paid_at END,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (new_amount_paid, new_amount_due, new_status, new_amount_due, invoice_id))

            # Update customer outstanding balance
            conn.execute("""
                UPDATE customers
                SET outstanding_balance = outstanding_balance - ?,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (request.amount, customer_id))

            conn.commit()

            # Return payment
            cursor = conn.execute("""
                SELECT * FROM payments WHERE id = ?
            """, (payment_id,))
            payment_row = cursor.fetchone()

            return PaymentResponse(
                id=payment_row[0],
                invoice_id=payment_row[1],
                amount=payment_row[2],
                payment_date=payment_row[3],
                payment_method=payment_row[4],
                reference_number=payment_row[5],
                notes=payment_row[6],
                created_at=payment_row[7]
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record payment: {str(e)}"
        )


@router.get("/{invoice_id}/payments", response_model=List[PaymentResponse])
async def list_payments(
    invoice_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """List all payments for invoice"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Verify invoice belongs to organization
            cursor = conn.execute("""
                SELECT id FROM invoices
                WHERE id = ? AND organization_id = ?
            """, (invoice_id, org_id))

            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found"
                )

            # Get payments
            cursor = conn.execute("""
                SELECT * FROM payments
                WHERE invoice_id = ?
                ORDER BY payment_date DESC
            """, (invoice_id,))

            return [
                PaymentResponse(
                    id=row[0],
                    invoice_id=row[1],
                    amount=row[2],
                    payment_date=row[3],
                    payment_method=row[4],
                    reference_number=row[5],
                    notes=row[6],
                    created_at=row[7]
                )
                for row in cursor.fetchall()
            ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Delete (cancel) invoice

    Can only delete draft invoices or cancel sent invoices
    Cannot delete paid invoices
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get invoice status
            cursor = conn.execute("""
                SELECT status FROM invoices
                WHERE id = ? AND organization_id = ?
            """, (invoice_id, org_id))

            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found"
                )

            invoice_status = row[0]

            if invoice_status == "paid":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete paid invoice"
                )

            if invoice_status == "draft":
                # Hard delete draft invoices
                conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
                conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
            else:
                # Soft delete (cancel) sent invoices
                conn.execute("""
                    UPDATE invoices
                    SET status = 'cancelled', updated_at = datetime('now')
                    WHERE id = ?
                """, (invoice_id,))

            conn.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

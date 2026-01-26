# app/routers/bills.py

from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from datetime import datetime
import uuid

from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/bills", tags=["bills"])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())

# =========================================================================
# MODELS
# =========================================================================

class BillCreate(BaseModel):
    """Create bill request"""
    vendor_id: str
    bill_number: str
    bill_date: str
    due_date: str
    amount: float
    description: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None

class BillUpdate(BaseModel):
    """Update bill request"""
    bill_number: Optional[str] = None
    bill_date: Optional[str] = None
    due_date: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None

class BillPaymentCreate(BaseModel):
    """Create bill payment"""
    amount: float
    payment_date: str
    payment_method: str
    reference: Optional[str] = None

class BillResponse(BaseModel):
    """Bill response"""
    id: str
    organization_id: str
    entity_id: Optional[str]
    vendor_id: str
    vendor_name: str
    bill_number: str
    bill_date: str
    due_date: str
    amount_total: float
    amount_paid: float
    amount_due: float
    status: str
    description: Optional[str]
    category: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str

class BillPaymentResponse(BaseModel):
    """Bill payment response"""
    id: str
    bill_id: str
    amount: float
    payment_date: str
    payment_method: str
    reference: Optional[str]
    created_at: str


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/", response_model=dict)
async def get_bills(
    request: Request,
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    bill_status: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get all bills for an organization

    Filter by entity_id and/or status if provided
    P0 FIX: Returns request_id on all responses.
    """
    request_id = _get_request_id(request)
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                b.id, b.organization_id, b.entity_id, b.vendor_id,
                v.name as vendor_name,
                b.bill_number, b.bill_date, b.due_date,
                b.amount as amount_total,
                COALESCE(b.amount_paid, '0.00') as amount_paid,
                b.amount_due,
                b.status, b.description, b.category, b.notes,
                b.created_at, b.updated_at
            FROM bills b
            JOIN vendors v ON b.vendor_id = v.id
            WHERE b.organization_id = ?
        """

        params = [org_id]

        if entity_id:
            query += " AND b.entity_id = ?"
            params.append(entity_id)

        if bill_status:
            query += " AND b.status = ?"
            params.append(bill_status)

        query += " ORDER BY b.due_date ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        bills = []
        for row in rows:
            bills.append(BillResponse(
                id=row[0],
                organization_id=row[1],
                entity_id=row[2],
                vendor_id=row[3],
                vendor_name=row[4],
                bill_number=row[5],
                bill_date=row[6],
                due_date=row[7],
                amount_total=float(row[8]) if row[8] else 0.0,
                amount_paid=float(row[9]) if row[9] else 0.0,
                amount_due=float(row[10]) if row[10] else 0.0,
                status=row[11],
                description=row[12],
                category=row[13],
                notes=row[14],
                created_at=row[15],
                updated_at=row[16]
            ).dict())

        return {"items": bills, "request_id": request_id}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "bills_list_failed", "message": str(e), "request_id": request_id}
        )


@router.post("/", response_model=BillResponse)
async def create_bill(
    bill: BillCreate,
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Create a new bill

    Creates a bill record for accounts payable tracking.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        bill_id = str(uuid.uuid4())

        # Verify vendor exists
        cursor.execute("SELECT id, name FROM vendors WHERE id = ?", (bill.vendor_id,))
        vendor = cursor.fetchone()
        if not vendor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vendor {bill.vendor_id} not found"
            )

        cursor.execute("""
            INSERT INTO bills (
                id, organization_id, entity_id, vendor_id,
                bill_number, bill_date, due_date, amount,
                amount_paid, amount_due, status, description,
                category, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            bill_id,
            org_id,
            entity_id,
            bill.vendor_id,
            bill.bill_number,
            bill.bill_date,
            bill.due_date,
            str(bill.amount),
            "0.00",
            str(bill.amount),
            "pending",
            bill.description,
            bill.category,
            bill.notes
        ))

        conn.commit()

        # Fetch the created bill
        cursor.execute("""
            SELECT
                b.id, b.organization_id, b.entity_id, b.vendor_id,
                v.name as vendor_name,
                b.bill_number, b.bill_date, b.due_date,
                b.amount, b.amount_paid, b.amount_due,
                b.status, b.description, b.category, b.notes,
                b.created_at, b.updated_at
            FROM bills b
            JOIN vendors v ON b.vendor_id = v.id
            WHERE b.id = ?
        """, (bill_id,))

        row = cursor.fetchone()

        return BillResponse(
            id=row[0],
            organization_id=row[1],
            entity_id=row[2],
            vendor_id=row[3],
            vendor_name=row[4],
            bill_number=row[5],
            bill_date=row[6],
            due_date=row[7],
            amount_total=float(row[8]) if row[8] else 0.0,
            amount_paid=float(row[9]) if row[9] else 0.0,
            amount_due=float(row[10]) if row[10] else 0.0,
            status=row[11],
            description=row[12],
            category=row[13],
            notes=row[14],
            created_at=row[15],
            updated_at=row[16]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating bill: {str(e)}"
        )


@router.get("/{bill_id}", response_model=BillResponse)
async def get_bill(
    bill_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Get a specific bill by ID"""
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                b.id, b.organization_id, b.entity_id, b.vendor_id,
                v.name as vendor_name,
                b.bill_number, b.bill_date, b.due_date,
                b.amount, b.amount_paid, b.amount_due,
                b.status, b.description, b.category, b.notes,
                b.created_at, b.updated_at
            FROM bills b
            JOIN vendors v ON b.vendor_id = v.id
            WHERE b.id = ?
        """, (bill_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bill {bill_id} not found"
            )

        return BillResponse(
            id=row[0],
            organization_id=row[1],
            entity_id=row[2],
            vendor_id=row[3],
            vendor_name=row[4],
            bill_number=row[5],
            bill_date=row[6],
            due_date=row[7],
            amount_total=float(row[8]) if row[8] else 0.0,
            amount_paid=float(row[9]) if row[9] else 0.0,
            amount_due=float(row[10]) if row[10] else 0.0,
            status=row[11],
            description=row[12],
            category=row[13],
            notes=row[14],
            created_at=row[15],
            updated_at=row[16]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching bill: {str(e)}"
        )


@router.put("/{bill_id}", response_model=BillResponse)
async def update_bill(
    bill_id: str,
    bill: BillUpdate,
    current_user_id: str = Depends(get_current_user_id)
):
    """Update an existing bill"""
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Build update query dynamically
        updates = []
        params = []

        if bill.bill_number is not None:
            updates.append("bill_number = ?")
            params.append(bill.bill_number)
        if bill.bill_date is not None:
            updates.append("bill_date = ?")
            params.append(bill.bill_date)
        if bill.due_date is not None:
            updates.append("due_date = ?")
            params.append(bill.due_date)
        if bill.amount is not None:
            updates.append("amount = ?")
            params.append(str(bill.amount))
        if bill.status is not None:
            updates.append("status = ?")
            params.append(bill.status)
        if bill.description is not None:
            updates.append("description = ?")
            params.append(bill.description)
        if bill.category is not None:
            updates.append("category = ?")
            params.append(bill.category)
        if bill.notes is not None:
            updates.append("notes = ?")
            params.append(bill.notes)

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        updates.append("updated_at = datetime('now')")
        params.append(bill_id)

        query = f"UPDATE bills SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bill {bill_id} not found"
            )

        # Fetch updated bill
        return await get_bill(bill_id, current_user_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating bill: {str(e)}"
        )


@router.delete("/{bill_id}")
async def delete_bill(
    bill_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Delete a bill"""
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bill {bill_id} not found"
            )

        return {"message": "Bill deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting bill: {str(e)}"
        )


@router.post("/{bill_id}/payments", response_model=BillPaymentResponse)
async def create_bill_payment(
    bill_id: str,
    payment: BillPaymentCreate,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Record a payment for a bill

    Updates bill status and amounts automatically
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify bill exists
        cursor.execute(
            "SELECT amount, amount_paid, amount_due FROM bills WHERE id = ?",
            (bill_id,)
        )
        bill_row = cursor.fetchone()
        if not bill_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bill {bill_id} not found"
            )

        total_amount = float(bill_row[0]) if bill_row[0] else 0.0
        current_paid = float(bill_row[1]) if bill_row[1] else 0.0

        # Calculate new amounts
        new_paid = current_paid + payment.amount
        new_due = total_amount - new_paid

        # Determine new status
        if new_due <= 0:
            new_status = "paid"
        elif new_paid > 0:
            new_status = "partial"
        else:
            new_status = "pending"

        # Create payment record (using notes field for now)
        payment_id = str(uuid.uuid4())
        payment_record = {
            "id": payment_id,
            "bill_id": bill_id,
            "amount": payment.amount,
            "payment_date": payment.payment_date,
            "payment_method": payment.payment_method,
            "reference": payment.reference,
            "created_at": datetime.now().isoformat()
        }

        # Update bill
        cursor.execute("""
            UPDATE bills
            SET amount_paid = ?,
                amount_due = ?,
                status = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (str(new_paid), str(new_due), new_status, bill_id))

        conn.commit()

        return BillPaymentResponse(**payment_record)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating payment: {str(e)}"
        )

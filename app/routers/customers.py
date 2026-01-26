# app/routers/customers.py

"""
Customer Management API
Handles customer CRUD operations for invoicing
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
import sqlite3
import uuid
from datetime import datetime

from ..db import DB_PATH
from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/customers", tags=["Customers"])


# =========================================================================
# MODELS
# =========================================================================

class CreateCustomerRequest(BaseModel):
    """Create customer request"""
    name: str = Field(..., min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    company_name: Optional[str] = Field(None, max_length=100)
    address_line1: Optional[str] = Field(None, max_length=200)
    address_line2: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    zip: Optional[str] = Field(None, pattern=r"^\d{5}(-\d{4})?$")
    country: str = Field(default="US")
    tax_id: Optional[str] = Field(None, max_length=50)
    payment_terms: int = Field(default=30, ge=0, le=365)
    notes: Optional[str] = None


class UpdateCustomerRequest(BaseModel):
    """Update customer request"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    company_name: Optional[str] = Field(None, max_length=100)
    address_line1: Optional[str] = Field(None, max_length=200)
    address_line2: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    zip: Optional[str] = Field(None, pattern=r"^\d{5}(-\d{4})?$")
    country: Optional[str] = None
    tax_id: Optional[str] = Field(None, max_length=50)
    payment_terms: Optional[int] = Field(None, ge=0, le=365)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerResponse(BaseModel):
    """Customer response"""
    id: str
    organization_id: str
    entity_id: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    company_name: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    country: str
    tax_id: Optional[str]
    payment_terms: int
    outstanding_balance: float
    total_invoiced: float = 0.0
    total_paid: float = 0.0
    active_invoices: int = 0
    is_active: bool
    notes: Optional[str]
    created_at: str
    updated_at: str


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    request: CreateCustomerRequest,
    entity_id: Optional[str] = None,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Create new customer

    Requires: create_transactions permission (or higher)
    """
    try:
        # TODO: Check permissions
        # require_permission("create_transactions")

        customer_id = f"customer-{uuid.uuid4().hex[:12]}"

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO customers (
                    id, organization_id, entity_id, name, email, phone,
                    company_name, address_line1, address_line2, city, state, zip,
                    country, tax_id, payment_terms, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                customer_id, org_id, entity_id,
                request.name, request.email, request.phone,
                request.company_name, request.address_line1, request.address_line2,
                request.city, request.state, request.zip, request.country,
                request.tax_id, request.payment_terms, request.notes
            ))
            conn.commit()

        # Fetch created customer
        return await get_customer(customer_id, org_id, current_user_id)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create customer: {str(e)}"
        )


@router.get("/", response_model=List[CustomerResponse])
async def list_customers(
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    active_only: bool = Query(True),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    List all customers for organization

    Filter by entity_id if multi-entity is enabled
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            query = """
                SELECT
                    c.*,
                    COALESCE(SUM(i.total_amount), 0) as total_invoiced,
                    COALESCE(SUM(i.amount_paid), 0) as total_paid,
                    COUNT(CASE WHEN i.status NOT IN ('paid', 'cancelled') THEN 1 END) as active_invoices
                FROM customers c
                LEFT JOIN invoices i ON c.id = i.customer_id
                WHERE c.organization_id = ?
            """
            params = [org_id]

            if entity_id:
                query += " AND c.entity_id = ?"
                params.append(entity_id)

            if active_only:
                query += " AND c.is_active = 1"

            query += " GROUP BY c.id ORDER BY c.name ASC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [
                CustomerResponse(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    entity_id=row["entity_id"],
                    name=row["name"],
                    email=row["email"],
                    phone=row["phone"],
                    company_name=row["company_name"],
                    address_line1=row["address_line1"],
                    address_line2=row["address_line2"],
                    city=row["city"],
                    state=row["state"],
                    zip=row["zip"],
                    country=row["country"],
                    tax_id=row["tax_id"],
                    payment_terms=row["payment_terms"],
                    outstanding_balance=row["outstanding_balance"],
                    total_invoiced=row["total_invoiced"],
                    total_paid=row["total_paid"],
                    active_invoices=row["active_invoices"],
                    is_active=bool(row["is_active"]),
                    notes=row["notes"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """Get customer by ID"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT
                    c.*,
                    COALESCE(SUM(i.total_amount), 0) as total_invoiced,
                    COALESCE(SUM(i.amount_paid), 0) as total_paid,
                    COUNT(CASE WHEN i.status NOT IN ('paid', 'cancelled') THEN 1 END) as active_invoices
                FROM customers c
                LEFT JOIN invoices i ON c.id = i.customer_id
                WHERE c.id = ? AND c.organization_id = ?
                GROUP BY c.id
            """, (customer_id, org_id))

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found"
                )

            return CustomerResponse(
                id=row["id"],
                organization_id=row["organization_id"],
                entity_id=row["entity_id"],
                name=row["name"],
                email=row["email"],
                phone=row["phone"],
                company_name=row["company_name"],
                address_line1=row["address_line1"],
                address_line2=row["address_line2"],
                city=row["city"],
                state=row["state"],
                zip=row["zip"],
                country=row["country"],
                tax_id=row["tax_id"],
                payment_terms=row["payment_terms"],
                outstanding_balance=row["outstanding_balance"],
                total_invoiced=row["total_invoiced"],
                total_paid=row["total_paid"],
                active_invoices=row["active_invoices"],
                is_active=bool(row["is_active"]),
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    request: UpdateCustomerRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Update customer

    Requires: edit_transactions permission (or higher)
    """
    try:
        # P0 Security: Column allowlist to prevent SQL injection
        allowed_fields = {
            'name', 'email', 'phone', 'company_name', 'address_line1',
            'address_line2', 'city', 'state', 'zip', 'country',
            'tax_id', 'payment_terms', 'notes', 'is_active'
        }

        # Build update query
        updates = request.model_dump(exclude_none=True)
        # Filter to allowed fields only
        updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        # Convert is_active to int
        if 'is_active' in updates:
            updates['is_active'] = int(updates['is_active'])

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = datetime('now')"
        values = list(updates.values()) + [customer_id, org_id]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                f"UPDATE customers SET {set_clause} WHERE id = ? AND organization_id = ?",
                values
            )

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found"
                )

            conn.commit()

        return await get_customer(customer_id, org_id, current_user_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Delete (deactivate) customer

    Soft delete - sets is_active = 0
    Cannot delete if customer has outstanding invoices
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Check for outstanding invoices
            cursor = conn.execute("""
                SELECT COUNT(*) FROM invoices
                WHERE customer_id = ? AND status NOT IN ('paid', 'cancelled')
            """, (customer_id,))

            if cursor.fetchone()[0] > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete customer with outstanding invoices"
                )

            # Soft delete
            cursor = conn.execute("""
                UPDATE customers
                SET is_active = 0, updated_at = datetime('now')
                WHERE id = ? AND organization_id = ?
            """, (customer_id, org_id))

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found"
                )

            conn.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

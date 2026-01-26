from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import sqlite3
from datetime import datetime
import uuid

from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


def _get_request_id(request: Request) -> str:
    """Get request_id from middleware or generate fallback."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())

# =========================================================================
# MODELS
# =========================================================================

class VendorCreate(BaseModel):
    """Create vendor request"""
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    payment_terms: int = 30  # net 30 days default
    ein: Optional[str] = None  # for 1099 tracking
    notes: Optional[str] = None

class VendorUpdate(BaseModel):
    """Update vendor request"""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    payment_terms: Optional[int] = None
    ein: Optional[str] = None
    notes: Optional[str] = None

class VendorResponse(BaseModel):
    """Vendor response"""
    id: str
    organization_id: str
    entity_id: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    payment_terms: int
    ein: Optional[str]
    notes: Optional[str]
    total_billed: float
    total_paid: float
    amount_owed: float
    active_bills: int
    is_active: bool
    created_at: str
    updated_at: str


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/", response_model=VendorResponse)
async def create_vendor(
    vendor: VendorCreate,
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Create a new vendor

    Creates a vendor record for tracking accounts payable.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        vendor_id = str(uuid.uuid4())

        cursor.execute("""
            INSERT INTO vendors (
                id, organization_id, entity_id, name, email, phone,
                address, city, state, zip, payment_terms, ein, notes,
                total_billed, total_paid, amount_owed, active_bills,
                is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id,
            org_id,
            entity_id,
            vendor.name,
            vendor.email,
            vendor.phone,
            vendor.address,
            vendor.city,
            vendor.state,
            vendor.zip,
            vendor.payment_terms,
            vendor.ein,
            vendor.notes,
            0.0,  # total_billed
            0.0,  # total_paid
            0.0,  # amount_owed
            0,    # active_bills
            1,    # is_active
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ))

        conn.commit()

        # Fetch the created vendor
        cursor.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        row = cursor.fetchone()
        conn.close()

        columns = [desc[0] for desc in cursor.description]
        vendor_dict = dict(zip(columns, row))

        return VendorResponse(**vendor_dict)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create vendor: {str(e)}"
        )


@router.get("/", response_model=dict)
async def list_vendors(
    request: Request,
    org_id: str = Depends(get_current_organization_id),
    entity_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    List all vendors for an organization

    Returns vendors with calculated totals (billed, paid, owed).
    P0 FIX: Returns request_id on all responses.
    """
    request_id = _get_request_id(request)
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM vendors WHERE organization_id = ?"
        params = [org_id]

        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)

        if is_active is not None:
            query += " AND is_active = ?"
            params.append(int(is_active))

        query += " ORDER BY name"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        columns = [desc[0] for desc in cursor.description]
        vendors = [dict(zip(columns, row)) for row in rows]

        return {
            "items": [VendorResponse(**vendor).dict() for vendor in vendors],
            "request_id": request_id
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "vendors_list_failed", "message": str(e), "request_id": request_id}
        )


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get a specific vendor by ID

    Returns vendor details with calculated totals.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found"
            )

        columns = [desc[0] for desc in cursor.description]
        vendor_dict = dict(zip(columns, row))

        return VendorResponse(**vendor_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get vendor: {str(e)}"
        )


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: str,
    updates: VendorUpdate,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Update a vendor

    Updates vendor information. Only provided fields will be updated.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if vendor exists
        cursor.execute("SELECT id FROM vendors WHERE id = ?", (vendor_id,))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found"
            )

        # Build update query dynamically
        update_fields = []
        params = []

        if updates.name is not None:
            update_fields.append("name = ?")
            params.append(updates.name)
        if updates.email is not None:
            update_fields.append("email = ?")
            params.append(updates.email)
        if updates.phone is not None:
            update_fields.append("phone = ?")
            params.append(updates.phone)
        if updates.address is not None:
            update_fields.append("address = ?")
            params.append(updates.address)
        if updates.city is not None:
            update_fields.append("city = ?")
            params.append(updates.city)
        if updates.state is not None:
            update_fields.append("state = ?")
            params.append(updates.state)
        if updates.zip is not None:
            update_fields.append("zip = ?")
            params.append(updates.zip)
        if updates.payment_terms is not None:
            update_fields.append("payment_terms = ?")
            params.append(updates.payment_terms)
        if updates.ein is not None:
            update_fields.append("ein = ?")
            params.append(updates.ein)
        if updates.notes is not None:
            update_fields.append("notes = ?")
            params.append(updates.notes)

        if not update_fields:
            # No updates provided, just return current vendor
            cursor.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
            row = cursor.fetchone()
            conn.close()
            columns = [desc[0] for desc in cursor.description]
            vendor_dict = dict(zip(columns, row))
            return VendorResponse(**vendor_dict)

        # Add updated_at
        update_fields.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(vendor_id)

        query = f"UPDATE vendors SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

        # Fetch updated vendor
        cursor.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        row = cursor.fetchone()
        conn.close()

        columns = [desc[0] for desc in cursor.description]
        vendor_dict = dict(zip(columns, row))

        return VendorResponse(**vendor_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update vendor: {str(e)}"
        )


@router.delete("/{vendor_id}")
async def delete_vendor(
    vendor_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Delete a vendor (soft delete)

    Marks vendor as inactive rather than deleting from database.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if vendor exists
        cursor.execute("SELECT id FROM vendors WHERE id = ?", (vendor_id,))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found"
            )

        # Soft delete (mark as inactive)
        cursor.execute("""
            UPDATE vendors
            SET is_active = 0, updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), vendor_id))

        conn.commit()
        conn.close()

        return {"success": True, "message": "Vendor deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete vendor: {str(e)}"
        )

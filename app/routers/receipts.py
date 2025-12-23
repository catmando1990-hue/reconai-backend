# app/routers/receipts.py

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from datetime import datetime
import uuid
import os
from pathlib import Path

try:
    from .auth import get_current_user_id
except ImportError:
    def get_current_user_id():
        return "system"

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

# =========================================================================
# MODELS
# =========================================================================

class ReceiptCreate(BaseModel):
    """Create receipt request"""
    file_name: str
    file_url: str
    vendor_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None

class ReceiptUpdate(BaseModel):
    """Update receipt request"""
    vendor_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None

class ReceiptResponse(BaseModel):
    """Receipt response"""
    id: str
    organization_id: str
    entity_id: Optional[str]
    file_name: str
    file_url: str
    vendor_name: Optional[str]
    amount: Optional[float]
    date: Optional[str]
    category: Optional[str]
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/", response_model=List[ReceiptResponse])
async def get_receipts(
    org_id: str,
    entity_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get all receipts for an organization

    Filter by entity_id and/or status if provided
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # First, ensure receipts table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_id TEXT,
                file_name TEXT NOT NULL,
                file_url TEXT NOT NULL,
                vendor_name TEXT,
                amount TEXT,
                date TEXT,
                category TEXT,
                description TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
            )
        """)

        query = """
            SELECT
                id, organization_id, entity_id, file_name, file_url,
                vendor_name, amount, date, category, description,
                status, created_at, updated_at
            FROM receipts
            WHERE organization_id = ?
        """

        params = [org_id]

        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        receipts = []
        for row in rows:
            receipts.append(ReceiptResponse(
                id=row[0],
                organization_id=row[1],
                entity_id=row[2],
                file_name=row[3],
                file_url=row[4],
                vendor_name=row[5],
                amount=float(row[6]) if row[6] else None,
                date=row[7],
                category=row[8],
                description=row[9],
                status=row[10],
                created_at=row[11],
                updated_at=row[12]
            ))

        return receipts

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching receipts: {str(e)}"
        )


@router.post("/", response_model=ReceiptResponse)
async def create_receipt(
    receipt: ReceiptCreate,
    org_id: str,
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Create a new receipt record

    Creates a receipt record for expense tracking.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Ensure receipts table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_id TEXT,
                file_name TEXT NOT NULL,
                file_url TEXT NOT NULL,
                vendor_name TEXT,
                amount TEXT,
                date TEXT,
                category TEXT,
                description TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
            )
        """)

        receipt_id = str(uuid.uuid4())

        cursor.execute("""
            INSERT INTO receipts (
                id, organization_id, entity_id, file_name, file_url,
                vendor_name, amount, date, category, description,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            receipt_id,
            org_id,
            entity_id,
            receipt.file_name,
            receipt.file_url,
            receipt.vendor_name,
            str(receipt.amount) if receipt.amount else None,
            receipt.date,
            receipt.category,
            receipt.description,
            "pending"
        ))

        conn.commit()

        # Fetch the created receipt
        cursor.execute("""
            SELECT
                id, organization_id, entity_id, file_name, file_url,
                vendor_name, amount, date, category, description,
                status, created_at, updated_at
            FROM receipts
            WHERE id = ?
        """, (receipt_id,))

        row = cursor.fetchone()

        return ReceiptResponse(
            id=row[0],
            organization_id=row[1],
            entity_id=row[2],
            file_name=row[3],
            file_url=row[4],
            vendor_name=row[5],
            amount=float(row[6]) if row[6] else None,
            date=row[7],
            category=row[8],
            description=row[9],
            status=row[10],
            created_at=row[11],
            updated_at=row[12]
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating receipt: {str(e)}"
        )


@router.post("/upload")
async def upload_receipt(
    file: UploadFile = File(...),
    org_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Upload a receipt file with AES-256 encryption

    Files are encrypted at rest using AES-256-GCM before being stored.
    """
    try:
        from app.db import UPLOADS_DIR
        from app.utils.encryption import get_encryption_service

        # Get encryption service
        encryption_service = get_encryption_service()

        # Create organization uploads directory
        org_uploads_dir = UPLOADS_DIR / (org_id or "default")
        org_uploads_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename with .enc extension
        file_ext = Path(file.filename).suffix if file.filename else ".jpg"
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        encrypted_filename = f"{unique_filename}.enc"
        temp_file_path = org_uploads_dir / unique_filename
        encrypted_file_path = org_uploads_dir / encrypted_filename

        # Read uploaded file content
        content = await file.read()

        # Save temporarily (for encryption)
        with open(temp_file_path, "wb") as f:
            f.write(content)

        # Encrypt the file using AES-256-GCM
        encryption_service.encrypt_file(str(temp_file_path), str(encrypted_file_path))

        # Delete unencrypted temporary file
        temp_file_path.unlink()

        # Create receipt record
        receipt_data = ReceiptCreate(
            file_name=file.filename or unique_filename,
            file_url=f"/uploads/{org_id or 'default'}/{encrypted_filename}",
            vendor_name=None,
            amount=None,
            date=datetime.now().date().isoformat(),
            category=None,
            description=f"Uploaded receipt: {file.filename} (encrypted with AES-256)"
        )

        receipt = await create_receipt(
            receipt_data,
            org_id or "default-org",
            entity_id,
            current_user_id
        )

        return {
            "message": "Receipt uploaded and encrypted successfully (AES-256)",
            "receipt": receipt,
            "encrypted": True,
            "encryption": "AES-256-GCM"
        }

    except Exception as e:
        # Clean up any temporary files on error
        if 'temp_file_path' in locals() and temp_file_path.exists():
            temp_file_path.unlink()
        if 'encrypted_file_path' in locals() and encrypted_file_path.exists():
            encrypted_file_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading receipt: {str(e)}"
        )


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Get a specific receipt by ID"""
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id, organization_id, entity_id, file_name, file_url,
                vendor_name, amount, date, category, description,
                status, created_at, updated_at
            FROM receipts
            WHERE id = ?
        """, (receipt_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receipt {receipt_id} not found"
            )

        return ReceiptResponse(
            id=row[0],
            organization_id=row[1],
            entity_id=row[2],
            file_name=row[3],
            file_url=row[4],
            vendor_name=row[5],
            amount=float(row[6]) if row[6] else None,
            date=row[7],
            category=row[8],
            description=row[9],
            status=row[10],
            created_at=row[11],
            updated_at=row[12]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching receipt: {str(e)}"
        )


@router.put("/{receipt_id}", response_model=ReceiptResponse)
async def update_receipt(
    receipt_id: str,
    receipt: ReceiptUpdate,
    current_user_id: str = Depends(get_current_user_id)
):
    """Update an existing receipt"""
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Build update query dynamically
        updates = []
        params = []

        if receipt.vendor_name is not None:
            updates.append("vendor_name = ?")
            params.append(receipt.vendor_name)
        if receipt.amount is not None:
            updates.append("amount = ?")
            params.append(str(receipt.amount))
        if receipt.date is not None:
            updates.append("date = ?")
            params.append(receipt.date)
        if receipt.category is not None:
            updates.append("category = ?")
            params.append(receipt.category)
        if receipt.status is not None:
            updates.append("status = ?")
            params.append(receipt.status)
        if receipt.description is not None:
            updates.append("description = ?")
            params.append(receipt.description)

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        updates.append("updated_at = datetime('now')")
        params.append(receipt_id)

        query = f"UPDATE receipts SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receipt {receipt_id} not found"
            )

        # Fetch updated receipt
        return await get_receipt(receipt_id, current_user_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating receipt: {str(e)}"
        )


@router.get("/{receipt_id}/download")
async def download_receipt(
    receipt_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Download and decrypt a receipt file

    Decrypts the AES-256 encrypted file on the fly for download.
    """
    try:
        from app.db import get_db_connection, UPLOADS_DIR
        from app.utils.encryption import get_encryption_service
        from fastapi.responses import FileResponse
        import tempfile

        # Get receipt record
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT file_name, file_url FROM receipts WHERE id = ?", (receipt_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receipt {receipt_id} not found"
            )

        original_filename = row[0]
        file_url = row[1]

        # Get encrypted file path
        encrypted_path = UPLOADS_DIR / file_url.lstrip("/uploads/")

        if not encrypted_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receipt file not found"
            )

        # Decrypt to temporary file
        encryption_service = get_encryption_service()
        temp_dir = Path(tempfile.gettempdir())
        decrypted_path = temp_dir / f"receipt_{receipt_id}_{original_filename}"

        encryption_service.decrypt_file(str(encrypted_path), str(decrypted_path))

        # Return decrypted file
        return FileResponse(
            path=str(decrypted_path),
            filename=original_filename,
            media_type="application/octet-stream"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading receipt: {str(e)}"
        )


@router.delete("/{receipt_id}")
async def delete_receipt(
    receipt_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Delete a receipt and its encrypted file"""
    try:
        from app.db import get_db_connection, UPLOADS_DIR

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get file path before deleting record
        cursor.execute("SELECT file_url FROM receipts WHERE id = ?", (receipt_id,))
        row = cursor.fetchone()

        cursor.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receipt {receipt_id} not found"
            )

        # Delete the encrypted file
        if row and row[0]:
            file_path = UPLOADS_DIR / row[0].lstrip("/uploads/")
            if file_path.exists():
                file_path.unlink()

        return {"message": "Receipt and encrypted file deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting receipt: {str(e)}"
        )

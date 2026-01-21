# app/routers/files.py

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile, Query
from fastapi.responses import FileResponse

from app.db import DB_PATH, UPLOADS_DIR
from app.models import TransactionsRequest, TransactionsResponse
from app.reconai_core.brain import ReconAIBrain
from app.reconai_core.bank_pdf import extract_text_from_pdf, parse_bank_statement_text
from app.reconai_core.parser import parse_text_lines
from app.services.document_service import (
    DocumentSource,
    DocumentStatus,
    get_document_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = name.replace("\r", "_").replace("\n", "_")
    return name or "upload.bin"


def _looks_like_csv(filename: str, content_type: Optional[str]) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    return fn.endswith(".csv") or ("csv" in ct)


def _looks_like_excel(filename: str, content_type: Optional[str]) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    return fn.endswith(".xlsx") or fn.endswith(".xls") or ("spreadsheet" in ct) or ("excel" in ct)


def _looks_like_pdf(filename: str, content_type: Optional[str]) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    return fn.endswith(".pdf") or ("pdf" in ct)


def _looks_like_image(filename: str, content_type: Optional[str]) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    return fn.endswith((".png", ".jpg", ".jpeg")) or ct.startswith("image/")


def _empty_transactions_response(goal: str, notes: Optional[list[str]] = None) -> TransactionsResponse:
    return TransactionsResponse(
        total_transactions=0,
        total_outflow=0.0,
        total_inflow=0.0,
        net=0.0,
        business_expenses=[],
        personal_expenses=[],
        transfers=[],
        uncertain=[],
        summary_notes=notes
        or [
            "No valid transactions were extracted from this file.",
            "If this is a PDF statement, it may be scanned (image-based) or use a bank-specific layout we haven't tuned yet.",
        ],
    )


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """
    Upload a file and create a document record.

    This endpoint creates a document record FIRST, then stores the file.
    Even if storage fails, the document exists with status=failed.

    Optional headers for document tracking:
    - X-Organization-ID: Organization context
    - X-User-ID: User context (for unauthenticated uploads, uses 'anonymous')
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    doc_service = get_document_service()
    ip_address = request.client.host if request.client else None

    # Use provided IDs or defaults for legacy compatibility
    org_id = x_organization_id or "legacy"
    user_id = x_user_id or "anonymous"

    upload_id = uuid4().hex
    original = _safe_name(file.filename or "upload.bin")

    # =================================================================
    # STEP 1: Create document record FIRST (before file storage)
    # =================================================================
    doc_result = doc_service.create_document(
        organization_id=org_id,
        user_id=user_id,
        filename=original,
        content_type=file.content_type,
        source=DocumentSource.UPLOAD,
        source_endpoint="/files/upload",
        ip_address=ip_address,
    )
    document_id = doc_result["document_id"]

    try:
        # =================================================================
        # STEP 2: Store file to disk
        # =================================================================
        ext = Path(original).suffix.lower()
        stored_name = f"{upload_id}{ext}" if ext else upload_id
        stored_path = UPLOADS_DIR / stored_name

        size = 0
        with stored_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)

        # Update document with file info
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                UPDATE documents
                SET file_size_bytes = ?, stored_path = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (size, str(stored_path), document_id),
            )
            conn.commit()

        # =================================================================
        # STEP 3: Mark validated (file stored successfully)
        # =================================================================
        doc_service.mark_validated(
            document_id=document_id,
            actor_id=user_id,
            details={"stored_path": str(stored_path), "file_size": size},
            ip_address=ip_address,
        )

        # =================================================================
        # STEP 4: Also store in legacy uploads table for backward compatibility
        # =================================================================
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO uploads (id, filename, content_type, stored_path, size_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (upload_id, original, file.content_type, str(stored_path), size),
            )
            conn.commit()

        return {
            "id": upload_id,
            "document_id": document_id,
            "filename": original,
            "content_type": file.content_type,
            "size_bytes": size,
            "status": DocumentStatus.VALIDATED.value,
            "download_url": f"/files/{upload_id}",
            "analyze_url": f"/files/{upload_id}/analyze",
        }

    except Exception as e:
        # =================================================================
        # FAILURE: Mark document as failed
        # =================================================================
        logger.exception(f"File storage failed for document {document_id}")
        doc_service.mark_failed(
            document_id=document_id,
            actor_id=user_id,
            failure_reason=str(e),
            ip_address=ip_address,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "document_id": document_id,
                "error": str(e),
                "status": DocumentStatus.FAILED.value,
            },
        )


@router.get("/{upload_id}")
def download_file(upload_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT filename, content_type, stored_path FROM uploads WHERE id=?",
            (upload_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    filename, content_type, stored_path = row
    path = Path(stored_path)

    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file missing on disk")

    return FileResponse(
        path=path,
        filename=filename,
        media_type=content_type or "application/octet-stream",
    )


@router.get("/", include_in_schema=False)
@router.get("")
def list_uploads(limit: int = 50):
    limit = max(1, min(limit, 200))
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT id, filename, content_type, size_bytes, created_at
            FROM uploads
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "filename": r[1],
            "content_type": r[2],
            "size_bytes": r[3],
            "created_at": r[4],
            "download_url": f"/files/{r[0]}",
            "analyze_url": f"/files/{r[0]}/analyze",
        }
        for r in rows
    ]


@router.post("/{upload_id}/analyze", response_model=TransactionsResponse)
def analyze_upload(
    upload_id: str,
    goal: str = Query("business_expenses", description="general_analysis | business_expenses | tax_prep"),
):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT filename, content_type, stored_path FROM uploads WHERE id=?",
            (upload_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Upload not found")

    filename, content_type, stored_path = row
    path = Path(stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file missing on disk")

    brain = ReconAIBrain()

    if _looks_like_csv(filename, content_type):
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        payload = TransactionsRequest(source_type="csv", goal=goal, raw_text=raw)
        return brain.analyze_transactions(payload)

    if _looks_like_excel(filename, content_type):
        try:
            import pandas as pd  # type: ignore
        except Exception:
            raise HTTPException(status_code=415, detail="Excel analysis requires pandas + openpyxl installed")
        df = pd.read_excel(path)
        raw_csv = df.to_csv(index=False)
        payload = TransactionsRequest(source_type="csv", goal=goal, raw_text=raw_csv)
        return brain.analyze_transactions(payload)

    if _looks_like_pdf(filename, content_type):
        text, pdf_notes = extract_text_from_pdf(str(path), max_pages=12)

        if not text:
            return _empty_transactions_response(goal, notes=pdf_notes)

        bank_res = parse_bank_statement_text(text)
        if bank_res.transactions:
            payload = TransactionsRequest(source_type="structured", goal=goal, transactions=bank_res.transactions)
            resp = brain.analyze_transactions(payload)
            resp.summary_notes = bank_res.notes + resp.summary_notes
            return resp

        generic = parse_text_lines(text)
        if generic.transactions:
            payload = TransactionsRequest(source_type="structured", goal=goal, transactions=generic.transactions)
            resp = brain.analyze_transactions(payload)
            resp.summary_notes = (bank_res.notes + generic.notes) + resp.summary_notes
            return resp

        return _empty_transactions_response(goal, notes=(pdf_notes + bank_res.notes))

    if _looks_like_image(filename, content_type):
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except Exception:
            raise HTTPException(
                status_code=415,
                detail="Image analysis requires pytesseract + Pillow AND system tesseract installed",
            )
        text = pytesseract.image_to_string(Image.open(str(path))).strip()
        parsed = parse_text_lines(text)
        if not parsed.transactions:
            return _empty_transactions_response(goal, notes=parsed.notes)
        payload = TransactionsRequest(source_type="structured", goal=goal, transactions=parsed.transactions)
        resp = brain.analyze_transactions(payload)
        resp.summary_notes = parsed.notes + resp.summary_notes
        return resp

    raise HTTPException(status_code=415, detail="Unsupported file type for analysis")

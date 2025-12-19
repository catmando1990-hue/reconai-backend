# app/routers/files.py

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse

from app.db import DB_PATH, UPLOADS_DIR
from app.models import TransactionsRequest, TransactionsResponse, Transaction
from app.reconai_core.brain import ReconAIBrain
from app.reconai_core.bank_pdf import extract_text_from_pdf, parse_bank_statement_text
from app.reconai_core.parser import parse_text_lines

router = APIRouter(prefix="/files", tags=["files"])


# ----------------------------
# helpers
# ----------------------------

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
    """Return a VALID empty TransactionsResponse."""
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


# ----------------------------
# upload + download
# ----------------------------

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload ANY file (csv, pdf, images, etc)."""
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    upload_id = uuid4().hex
    original = _safe_name(file.filename or "upload.bin")

    ext = Path(original).suffix.lower()
    stored_name = f"{upload_id}{ext}" if ext else upload_id
    stored_path = UPLOADS_DIR / stored_name

    size = 0
    with stored_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            out.write(chunk)
            size += len(chunk)

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
        "filename": original,
        "content_type": file.content_type,
        "size_bytes": size,
        "download_url": f"/files/{upload_id}",
        "analyze_url": f"/files/{upload_id}/analyze",
    }


@router.get("/{upload_id}")
def download_file(upload_id: str):
    """Download the uploaded file by id."""
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


# ----------------------------
# list uploads (supports /files and /files/)
# ----------------------------

@router.get("/", include_in_schema=False)
@router.get("")
def list_uploads(limit: int = 50):
    """List recent uploads."""
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


# ----------------------------
# analyze (all types)
# ----------------------------

@router.post("/{upload_id}/analyze", response_model=TransactionsResponse)
def analyze_upload(
    upload_id: str,
    goal: str = Query("business_expenses", description="general_analysis | business_expenses | tax_prep"),
):
    """
    Analyze an uploaded file server-side.

    Supported:
    - CSV: direct
    - XLSX/XLS: converted to CSV text, then analyzed
    - PDF: bank-aware extraction -> structured transactions -> analyzed
    - Images (png/jpg/jpeg): OCR (if installed) -> text parse -> analyzed

    If we can't extract any transactions, we return a valid empty response (200 OK).
    """
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

    # ---------- CSV ----------
    if _looks_like_csv(filename, content_type):
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        payload = TransactionsRequest(source_type="csv", goal=goal, raw_text=raw)
        return brain.analyze_transactions(payload)

    # ---------- EXCEL ----------
    if _looks_like_excel(filename, content_type):
        try:
            import pandas as pd  # type: ignore
        except Exception:
            raise HTTPException(status_code=415, detail="Excel analysis requires pandas + openpyxl installed")

        df = pd.read_excel(path)
        raw_csv = df.to_csv(index=False)
        payload = TransactionsRequest(source_type="csv", goal=goal, raw_text=raw_csv)
        return brain.analyze_transactions(payload)

    # ---------- PDF (bank-aware) ----------
    if _looks_like_pdf(filename, content_type):
        text, pdf_notes = extract_text_from_pdf(str(path), max_pages=12)
        if not text:
            # likely scanned / image-based statement (OCR for PDF pages is a separate step)
            return _empty_transactions_response(goal, notes=pdf_notes)

        bank_res = parse_bank_statement_text(text)

        # If we got structured transactions, analyze them directly
        if bank_res.transactions:
            payload = TransactionsRequest(
                source_type="structured",
                goal=goal,
                transactions=bank_res.transactions,
            )
            resp = brain.analyze_transactions(payload)
            # prepend bank notes to summary_notes
            resp.summary_notes = bank_res.notes + resp.summary_notes
            return resp

        # Fallback: try generic text-line parsing
        generic = parse_text_lines(text)
        if generic.transactions:
            payload = TransactionsRequest(source_type="structured", goal=goal, transactions=generic.transactions)
            resp = brain.analyze_transactions(payload)
            resp.summary_notes = (bank_res.notes + generic.notes) + resp.summary_notes
            return resp

        return _empty_transactions_response(goal, notes=(pdf_notes + bank_res.notes))

    # ---------- IMAGE (OCR -> parse) ----------
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

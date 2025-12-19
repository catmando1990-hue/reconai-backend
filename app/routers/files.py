from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse

from app.db import DB_PATH, UPLOADS_DIR
from app.models import TransactionsRequest, TransactionsResponse
from app.reconai_core.brain import ReconAIBrain

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


def _csv_header() -> str:
    return "date,description,amount\n"


def _to_csv_row(date: str, desc: str, amt: str) -> str:
    # minimal CSV escaping
    desc = (desc or "").replace('"', '""')
    date = (date or "").replace('"', '""')
    amt = (amt or "").replace('"', '""')
    return f'"{date}","{desc}","{amt}"\n'


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload ANY file (csv, pdf, images, etc).
    Stores it under DATA_DIR/uploads and records metadata in SQLite.
    """
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


@router.post("/{upload_id}/analyze", response_model=TransactionsResponse)
def analyze_upload(
    upload_id: str,
    goal: str = Query("business_expenses", description="general_analysis | business_expenses | tax_prep"),
):
    """
    Analyze an uploaded file server-side.

    Supported:
    - CSV: direct (current behavior)
    - XLSX/XLS: converted to CSV text, then analyzed
    - PDF: best-effort text extraction + heuristic parsing into CSV, then analyzed
    - Images (png/jpg/jpeg): OCR (if installed) + heuristic parsing into CSV, then analyzed
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

    # ---------- CSV (existing) ----------
    if _looks_like_csv(filename, content_type):
        try:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

        payload = TransactionsRequest(
            source_type="csv",
            goal=goal,
            raw_text=raw,
        )
        return brain.analyze_transactions(payload)

    # ---------- EXCEL (.xlsx/.xls) -> CSV ----------
    if _looks_like_excel(filename, content_type):
        try:
            import pandas as pd  # type: ignore
        except Exception:
            raise HTTPException(
                status_code=415,
                detail="Excel analysis requires pandas + openpyxl installed on the backend",
            )

        try:
            df = pd.read_excel(path)
            raw_csv = df.to_csv(index=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {e}")

        payload = TransactionsRequest(
            source_type="csv",
            goal=goal,
            raw_text=raw_csv,
        )
        return brain.analyze_transactions(payload)

    # ---------- PDF -> text -> heuristic tx lines -> CSV ----------
    if _looks_like_pdf(filename, content_type):
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            raise HTTPException(
                status_code=415,
                detail="PDF analysis requires pypdf installed on the backend",
            )

        try:
            reader = PdfReader(str(path))
            text_parts = []
            for page in reader.pages[:8]:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(text_parts)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read PDF: {e}")

        date_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
        amt_re = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")

        raw_csv = _csv_header()
        parsed = 0

        for ln in [l.strip() for l in text.splitlines() if l.strip()]:
            mdate = date_re.search(ln)
            if not mdate:
                continue
            amts = amt_re.findall(ln)
            if not amts:
                continue

            date = mdate.group(1)
            amt = amts[-1]
            desc = ln.replace(date, "").replace(amt, "").strip() or "PDF transaction"

            raw_csv += _to_csv_row(date, desc, amt)
            parsed += 1

        if parsed == 0:
            raw_csv = _csv_header()

        payload = TransactionsRequest(
            source_type="csv",
            goal=goal,
            raw_text=raw_csv,
        )
        return brain.analyze_transactions(payload)

    # ---------- IMAGE -> OCR -> heuristic tx lines -> CSV ----------
    if _looks_like_image(filename, content_type):
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except Exception:
            raise HTTPException(
                status_code=415,
                detail="Image analysis requires pytesseract + Pillow AND system tesseract installed on the backend",
            )

        try:
            img = Image.open(str(path))
            text = pytesseract.image_to_string(img)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed OCR: {e}")

        date_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
        amt_re = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")

        raw_csv = _csv_header()
        parsed = 0

        for ln in [l.strip() for l in text.splitlines() if l.strip()]:
            mdate = date_re.search(ln)
            if not mdate:
                continue
            amts = amt_re.findall(ln)
            if not amts:
                continue

            date = mdate.group(1)
            amt = amts[-1]
            desc = ln.replace(date, "").replace(amt, "").strip() or "OCR transaction"

            raw_csv += _to_csv_row(date, desc, amt)
            parsed += 1

        if parsed == 0:
            raw_csv = _csv_header()

        payload = TransactionsRequest(
            source_type="csv",
            goal=goal,
            raw_text=raw_csv,
        )
        return brain.analyze_transactions(payload)

    raise HTTPException(status_code=415, detail="Unsupported file type for analysis")

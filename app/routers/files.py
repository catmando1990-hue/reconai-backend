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
    return (
        fn.endswith(".xlsx")
        or fn.endswith(".xls")
        or ("spreadsheet" in ct)
        or ("excel" in ct)
    )


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
    desc = (desc or "").replace('"', '""')
    date = (date or "").replace('"', '""')
    amt = (amt or "").replace('"', '""')
    return f'"{date}","{desc}","{amt}"\n'


def _empty_transactions_response(goal: str, raw_text: Optional[str] = None) -> dict:
    """
    Return a valid empty analysis response (HTTP 200) so the frontend doesn't error
    when we can't extract transactions from a PDF/image.
    """
    return {
        "schema_version": "1.0.0",
        "goal": goal,
        "total_transactions": 0,
        "total_inflow": 0,
        "total_outflow": 0,
        "net": 0,
        "transactions": [],
        "business_expenses": [],
        "personal_expenses": [],
        "transfers": [],
        "uncertain": [],
        "raw_text": raw_text,
    }


# ----------------------------
# upload + download
# ----------------------------

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
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
            chunk = await file.read(1024 * 1024)
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
# list uploads (handles /files and /files/)
# ----------------------------

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


# ----------------------------
# analyze (ALL file types)
# ----------------------------

@router.post("/{upload_id}/analyze", response_model=TransactionsResponse)
def analyze_upload(
    upload_id: str,
    goal: str = Query(
        "business_expenses",
        description="general_analysis | business_expenses | tax_prep",
    ),
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

    # ---- CSV ----
    if _looks_like_csv(filename, content_type):
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        return brain.analyze_transactions(
            TransactionsRequest(
                source_type="csv",
                goal=goal,
                raw_text=raw,
            )
        )

    # ---- EXCEL ----
    if _looks_like_excel(filename, content_type):
        import pandas as pd
        df = pd.read_excel(path)
        raw_csv = df.to_csv(index=False)
        return brain.analyze_transactions(
            TransactionsRequest(
                source_type="csv",
                goal=goal,
                raw_text=raw_csv,
            )
        )

    # ---- PDF ----
    if _looks_like_pdf(filename, content_type):
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages[:8]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(text_parts)

        # heuristic: date + amount on same line
        date_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
        amt_re = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")

        raw_csv = _csv_header()
        parsed = 0

        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            mdate = date_re.search(ln)
            amts = amt_re.findall(ln)
            if not mdate or not amts:
                continue

            date = mdate.group(1)
            amt = amts[-1]
            desc = ln.replace(date, "").replace(amt, "").strip() or "PDF transaction"

            raw_csv += _to_csv_row(date, desc, amt)
            parsed += 1

        # If we couldn't parse any rows, return a VALID empty response (200 OK)
        if parsed == 0:
            return _empty_transactions_response(goal=goal, raw_text=text)

        return brain.analyze_transactions(
            TransactionsRequest(
                source_type="csv",
                goal=goal,
                raw_text=raw_csv,
            )
        )

    # ---- IMAGE (OCR) ----
    if _looks_like_image(filename, content_type):
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(path))

        date_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
        amt_re = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")

        raw_csv = _csv_header()
        parsed = 0

        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            mdate = date_re.search(ln)
            amts = amt_re.findall(ln)
            if not mdate or not amts:
                continue

            date = mdate.group(1)
            amt = amts[-1]
            desc = ln.replace(date, "").replace(amt, "").strip() or "OCR transaction"

            raw_csv += _to_csv_row(date, desc, amt)
            parsed += 1

        if parsed == 0:
            return _empty_transactions_response(goal=goal, raw_text=text)

        return brain.analyze_transactions(
            TransactionsRequest(
                source_type="csv",
                goal=goal,
                raw_text=raw_csv,
            )
        )

    raise HTTPException(status_code=415, detail="Unsupported file type for analysis")

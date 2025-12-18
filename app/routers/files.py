# app/routers/files.py

from __future__ import annotations

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
    Step 8: Analyze an uploaded CSV file server-side.

    - Only CSV is supported right now.
    - For PDF/images, upload+download works, but analysis will return 415.
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

    if not _looks_like_csv(filename, content_type):
        raise HTTPException(status_code=415, detail="Only CSV uploads can be analyzed right now")

    path = Path(stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file missing on disk")

    # Read CSV bytes as UTF-8 (tolerate BOM)
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    payload = TransactionsRequest(
        source_type="csv",
        goal=goal,          # pydantic will validate if your model uses Literals; keep values consistent
        raw_text=raw,
    )

    brain = ReconAIBrain()
    return brain.analyze_transactions(payload)

# app/routers/files.py

from __future__ import annotations

import sqlite3 
import re
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


[{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"router\" is not defined",
	"source": "Pylance",
	"startLineNumber": 1,
	"startColumn": 2,
	"endLineNumber": 1,
	"endColumn": 8,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"TransactionsResponse\" is not defined",
	"source": "Pylance",
	"startLineNumber": 1,
	"startColumn": 53,
	"endLineNumber": 1,
	"endColumn": 73,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"Query\" is not defined",
	"source": "Pylance",
	"startLineNumber": 4,
	"startColumn": 17,
	"endLineNumber": 4,
	"endColumn": 22,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"sqlite3\" is not defined",
	"source": "Pylance",
	"startLineNumber": 15,
	"startColumn": 10,
	"endLineNumber": 15,
	"endColumn": 17,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"DB_PATH\" is not defined",
	"source": "Pylance",
	"startLineNumber": 15,
	"startColumn": 26,
	"endLineNumber": 15,
	"endColumn": 33,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 23,
	"startColumn": 15,
	"endLineNumber": 23,
	"endColumn": 28,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"Path\" is not defined",
	"source": "Pylance",
	"startLineNumber": 26,
	"startColumn": 12,
	"endLineNumber": 26,
	"endColumn": 16,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 29,
	"startColumn": 15,
	"endLineNumber": 29,
	"endColumn": 28,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_looks_like_csv\" is not defined",
	"source": "Pylance",
	"startLineNumber": 32,
	"startColumn": 8,
	"endLineNumber": 32,
	"endColumn": 23,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 36,
	"startColumn": 19,
	"endLineNumber": 36,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"TransactionsRequest\" is not defined",
	"source": "Pylance",
	"startLineNumber": 38,
	"startColumn": 19,
	"endLineNumber": 38,
	"endColumn": 38,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"ReconAIBrain\" is not defined",
	"source": "Pylance",
	"startLineNumber": 43,
	"startColumn": 17,
	"endLineNumber": 43,
	"endColumn": 29,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_looks_like_excel\" is not defined",
	"source": "Pylance",
	"startLineNumber": 47,
	"startColumn": 8,
	"endLineNumber": 47,
	"endColumn": 25,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 51,
	"startColumn": 19,
	"endLineNumber": 51,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 60,
	"startColumn": 19,
	"endLineNumber": 60,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"TransactionsRequest\" is not defined",
	"source": "Pylance",
	"startLineNumber": 62,
	"startColumn": 19,
	"endLineNumber": 62,
	"endColumn": 38,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"ReconAIBrain\" is not defined",
	"source": "Pylance",
	"startLineNumber": 67,
	"startColumn": 17,
	"endLineNumber": 67,
	"endColumn": 29,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_looks_like_pdf\" is not defined",
	"source": "Pylance",
	"startLineNumber": 71,
	"startColumn": 8,
	"endLineNumber": 71,
	"endColumn": 23,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 75,
	"startColumn": 19,
	"endLineNumber": 75,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 90,
	"startColumn": 19,
	"endLineNumber": 90,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"re\" is not defined",
	"source": "Pylance",
	"startLineNumber": 92,
	"startColumn": 19,
	"endLineNumber": 92,
	"endColumn": 21,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"re\" is not defined",
	"source": "Pylance",
	"startLineNumber": 93,
	"startColumn": 18,
	"endLineNumber": 93,
	"endColumn": 20,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_csv_header\" is not defined",
	"source": "Pylance",
	"startLineNumber": 95,
	"startColumn": 19,
	"endLineNumber": 95,
	"endColumn": 30,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_to_csv_row\" is not defined",
	"source": "Pylance",
	"startLineNumber": 110,
	"startColumn": 24,
	"endLineNumber": 110,
	"endColumn": 35,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_csv_header\" is not defined",
	"source": "Pylance",
	"startLineNumber": 115,
	"startColumn": 23,
	"endLineNumber": 115,
	"endColumn": 34,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"TransactionsRequest\" is not defined",
	"source": "Pylance",
	"startLineNumber": 117,
	"startColumn": 19,
	"endLineNumber": 117,
	"endColumn": 38,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"ReconAIBrain\" is not defined",
	"source": "Pylance",
	"startLineNumber": 122,
	"startColumn": 17,
	"endLineNumber": 122,
	"endColumn": 29,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_looks_like_image\" is not defined",
	"source": "Pylance",
	"startLineNumber": 126,
	"startColumn": 8,
	"endLineNumber": 126,
	"endColumn": 25,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 131,
	"startColumn": 19,
	"endLineNumber": 131,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 140,
	"startColumn": 19,
	"endLineNumber": 140,
	"endColumn": 32,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"re\" is not defined",
	"source": "Pylance",
	"startLineNumber": 142,
	"startColumn": 19,
	"endLineNumber": 142,
	"endColumn": 21,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"re\" is not defined",
	"source": "Pylance",
	"startLineNumber": 143,
	"startColumn": 18,
	"endLineNumber": 143,
	"endColumn": 20,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_csv_header\" is not defined",
	"source": "Pylance",
	"startLineNumber": 145,
	"startColumn": 19,
	"endLineNumber": 145,
	"endColumn": 30,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_to_csv_row\" is not defined",
	"source": "Pylance",
	"startLineNumber": 160,
	"startColumn": 24,
	"endLineNumber": 160,
	"endColumn": 35,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"_csv_header\" is not defined",
	"source": "Pylance",
	"startLineNumber": 164,
	"startColumn": 23,
	"endLineNumber": 164,
	"endColumn": 34,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"TransactionsRequest\" is not defined",
	"source": "Pylance",
	"startLineNumber": 166,
	"startColumn": 19,
	"endLineNumber": 166,
	"endColumn": 38,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"ReconAIBrain\" is not defined",
	"source": "Pylance",
	"startLineNumber": 171,
	"startColumn": 17,
	"endLineNumber": 171,
	"endColumn": 29,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/app/routers/files.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "\"HTTPException\" is not defined",
	"source": "Pylance",
	"startLineNumber": 174,
	"startColumn": 11,
	"endLineNumber": 174,
	"endColumn": 24,
	"origin": "extHost1"
},{
	"resource": "/c:/Users/HP/Desktop/reconai-backend/tests/test_exports_csv.py",
	"owner": "Pylance2",
	"code": {
		"value": "reportMissingImports",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportMissingImports.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "Import \"pytest\" could not be resolved",
	"source": "Pylance",
	"startLineNumber": 9,
	"startColumn": 8,
	"endLineNumber": 9,
	"endColumn": 14,
	"origin": "extHost1"
}]

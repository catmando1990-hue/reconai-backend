# intelligence_export_api.py
# STEP 4B — Evidence Retention & Manual Exports
# Manual export of intelligence results with policy acknowledgement + audit logging.
# NO auto-export, NO background jobs — manual-run only.

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.guardrails import CONFIDENCE_THRESHOLD

router = APIRouter(prefix="/api/intelligence/export", tags=["intelligence-export"])


# Evidence reference storage (IDs only, not full data)
def _init_evidence_table():
    """Create evidence_refs table if it doesn't exist."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence_refs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    org_id TEXT,
                    result_type TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    explanation TEXT,
                    evidence_snapshot TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_evidence_user
                ON evidence_refs(user_id, created_at DESC)
            """)
            conn.commit()
    except Exception:
        pass  # Table may already exist


def _log_export_audit(
    user_id: str,
    org_id: Optional[str],
    export_type: str,
    record_count: int,
    policy_acknowledged: bool,
):
    """Log export action to audit_logs table."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_logs (
                    id, timestamp, user_id, organization_id, action,
                    resource_type, resource_id, method, path, status_code,
                    ip_address, user_agent, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                user_id,
                org_id,
                "DATA_EXPORT",
                "intelligence_evidence",
                export_type,
                "POST",
                f"/api/intelligence/export/{export_type}",
                200,
                "api",
                "intelligence-export-api",
                json.dumps({
                    "record_count": record_count,
                    "policy_acknowledged": policy_acknowledged,
                    "export_type": export_type,
                })
            ))
            conn.commit()
    except Exception as e:
        print(f"Audit log error: {e}")


@router.post("/csv")
async def export_intelligence_csv(
    ctx: AuthContext = Depends(get_current_context),
    result_type: str = Query(..., description="Type: duplicates, categorization, cashflow"),
    policy_acknowledged: bool = Query(False, description="User must acknowledge export policy"),
    filename: Optional[str] = Query(None, description="Custom filename"),
):
    """
    POST /api/intelligence/export/csv

    Export intelligence results to CSV with policy acknowledgement.
    Requires explicit policy_acknowledged=true parameter.
    Every export is audit logged.
    """
    # Enforce policy acknowledgement
    if not policy_acknowledged:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "POLICY_ACK_REQUIRED",
                "message": "You must acknowledge the export policy before downloading. Set policy_acknowledged=true.",
            }
        )

    # Get stored evidence refs for this user
    _init_evidence_table()
    records = []

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT id, result_type, result_id, confidence, explanation, evidence_snapshot, created_at
                FROM evidence_refs
                WHERE user_id = ? AND result_type = ?
                ORDER BY created_at DESC
                LIMIT 1000
            """, (ctx["user_id"], result_type))
            records = [dict(row) for row in cursor.fetchall()]
    except Exception:
        pass

    # Log the export
    _log_export_audit(
        user_id=ctx["user_id"],
        org_id=ctx.get("org_id"),
        export_type=f"csv_{result_type}",
        record_count=len(records),
        policy_acknowledged=True,
    )

    # Generate CSV
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", "result_type", "result_id", "confidence", "explanation", "created_at"])

    for record in records:
        writer.writerow([
            record["id"],
            record["result_type"],
            record["result_id"],
            record["confidence"],
            record["explanation"] or "",
            record["created_at"],
        ])

    csv_content = output.getvalue()
    safe_filename = filename or f"intelligence-{result_type}-export.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post("/json")
async def export_intelligence_json(
    ctx: AuthContext = Depends(get_current_context),
    result_type: str = Query(..., description="Type: duplicates, categorization, cashflow"),
    policy_acknowledged: bool = Query(False, description="User must acknowledge export policy"),
):
    """
    POST /api/intelligence/export/json

    Export intelligence results to JSON with policy acknowledgement.
    Requires explicit policy_acknowledged=true parameter.
    Every export is audit logged.
    """
    # Enforce policy acknowledgement
    if not policy_acknowledged:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "POLICY_ACK_REQUIRED",
                "message": "You must acknowledge the export policy before downloading. Set policy_acknowledged=true.",
            }
        )

    # Get stored evidence refs for this user
    _init_evidence_table()
    records = []

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT id, result_type, result_id, confidence, explanation, evidence_snapshot, created_at
                FROM evidence_refs
                WHERE user_id = ? AND result_type = ?
                ORDER BY created_at DESC
                LIMIT 1000
            """, (ctx["user_id"], result_type))
            records = [dict(row) for row in cursor.fetchall()]

            # Parse evidence_snapshot JSON
            for record in records:
                if record.get("evidence_snapshot"):
                    try:
                        record["evidence"] = json.loads(record["evidence_snapshot"])
                    except Exception:
                        record["evidence"] = []
                del record["evidence_snapshot"]
    except Exception:
        pass

    # Log the export
    _log_export_audit(
        user_id=ctx["user_id"],
        org_id=ctx.get("org_id"),
        export_type=f"json_{result_type}",
        record_count=len(records),
        policy_acknowledged=True,
    )

    return {
        "ok": True,
        "export_type": result_type,
        "record_count": len(records),
        "records": records,
        "exported_at": datetime.utcnow().isoformat(),
        "policy_acknowledged": True,
    }


@router.post("/retain")
async def retain_evidence_ref(
    ctx: AuthContext = Depends(get_current_context),
    result_type: str = Query(..., description="Type: duplicates, categorization, cashflow"),
    result_id: str = Query(..., description="ID of the intelligence result"),
    confidence: float = Query(..., ge=0.0, le=1.0, description="Confidence score"),
    explanation: str = Query(None, description="AI explanation"),
    evidence: str = Query(None, description="JSON-encoded evidence array"),
):
    """
    POST /api/intelligence/export/retain

    Persist an evidence reference (IDs only).
    Called when user views/acknowledges an intelligence result.
    """
    _init_evidence_table()

    ref_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO evidence_refs (
                    id, user_id, org_id, result_type, result_id,
                    confidence, explanation, evidence_snapshot, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ref_id,
                ctx["user_id"],
                ctx.get("org_id"),
                result_type,
                result_id,
                confidence,
                explanation,
                evidence,
                now,
            ))
            conn.commit()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "RETAIN_FAILED", "message": str(e)}
        )

    return {
        "ok": True,
        "ref_id": ref_id,
        "result_type": result_type,
        "result_id": result_id,
        "retained_at": now,
    }

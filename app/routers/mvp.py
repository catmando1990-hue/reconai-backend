from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.auth_context import AuthIdentity, get_current_identity, get_org_service
from app.db import DB_PATH
from app.errors import not_authorized, org_required
from app.models import Transaction, TransactionsRequest
from app.routers.transactions import analyze as analyze_transactions


router = APIRouter(tags=["mvp"])  # no prefix; required paths are root-level


def _parse_transactions_from_upload(file: UploadFile, raw: bytes) -> TransactionsRequest:
    filename = (file.filename or "").lower()

    if filename.endswith(".json"):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

        if isinstance(payload, dict) and "transactions" in payload:
            payload_transactions = payload.get("transactions")
        else:
            payload_transactions = payload

        if not isinstance(payload_transactions, list):
            raise HTTPException(status_code=400, detail="JSON must be a list of transactions or {transactions: [...]}.")

        transactions: List[Transaction] = []
        for item in payload_transactions:
            if not isinstance(item, dict):
                continue
            transactions.append(Transaction(**item))

        return TransactionsRequest(source_type="structured", transactions=transactions)

    if filename.endswith(".csv"):
        text = raw.decode("utf-8", errors="replace")
        return TransactionsRequest(source_type="csv", raw_text=text)

    # fallback: treat as semi-structured text
    text = raw.decode("utf-8", errors="replace")
    return TransactionsRequest(source_type="text", raw_text=text)


def _resolve_mvp_org_id(
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
    identity: AuthIdentity = Depends(get_current_identity),
):
    service = get_org_service()

    if x_organization_id:
        member = service.get_organization_member(x_organization_id, identity["user_id"])
        if not member:
            not_authorized("Not a member of requested organization")
        return x_organization_id

    default_org_id = identity.get("default_org_id")
    if default_org_id:
        return default_org_id

    org_required("Organization context required (set X-Organization-ID or default_org_id)")
    raise AssertionError("unreachable")


def _flatten_bucket(bucket: List[Transaction], classification: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tx in bucket:
        tx_id = tx.id or f"mvp-tx-{uuid.uuid4().hex}"
        tx_date = None
        if isinstance(tx.date, date):
            tx_date = tx.date.isoformat()
        elif tx.date is not None:
            tx_date = str(tx.date)

        rows.append(
            {
                "id": tx_id,
                "date": tx_date,
                "amount": float(tx.amount),
                "description": tx.description,
                "merchant": tx.merchant,
                "original_category": tx.original_category,
                "classification": classification,
                "reason": tx.reason,
            }
        )

    return rows


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    org_id: str = Depends(_resolve_mvp_org_id),
    identity: AuthIdentity = Depends(get_current_identity),
):
    """MVP upload endpoint for Phases 010–012.

    - Requires Authorization: Bearer <JWT>
    - Requires org context via X-Organization-ID header OR user.default_org_id
    - Stores flattened analyzed transactions into SQLite table: mvp_transactions
    """

    raw = await file.read()
    request = _parse_transactions_from_upload(file, raw)

    # Reuse existing analysis normalization
    analyzed = analyze_transactions(request)

    upload_id = f"mvp-upload-{uuid.uuid4().hex}"

    flattened: List[Dict[str, Any]] = []
    flattened.extend(_flatten_bucket(analyzed.business_expenses, "business"))
    flattened.extend(_flatten_bucket(analyzed.personal_expenses, "personal"))
    flattened.extend(_flatten_bucket(analyzed.transfers, "transfer"))
    flattened.extend(_flatten_bucket(analyzed.uncertain, "uncertain"))

    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO mvp_uploads (id, organization_id, user_id, filename)
            VALUES (?, ?, ?, ?)
            """,
            (upload_id, org_id, identity["user_id"], file.filename),
        )

        for row in flattened:
            conn.execute(
                """
                INSERT OR REPLACE INTO mvp_transactions (
                    id,
                    upload_id,
                    organization_id,
                    user_id,
                    tx_date,
                    amount,
                    description,
                    merchant,
                    original_category,
                    classification,
                    reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    upload_id,
                    org_id,
                    identity["user_id"],
                    row["date"],
                    row["amount"],
                    row["description"],
                    row["merchant"],
                    row["original_category"],
                    row["classification"],
                    row["reason"],
                ),
            )

        conn.commit()

    return {
        "upload_id": upload_id,
        "organization_id": org_id,
        "total_transactions": len(flattened),
    }


@router.get("/transactions")
async def list_transactions(
    upload_id: Optional[str] = None,
    limit: int = 200,
    org_id: str = Depends(_resolve_mvp_org_id),
    identity: AuthIdentity = Depends(get_current_identity),
):
    import sqlite3

    limit = max(1, min(limit, 2000))

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT
                id, upload_id, organization_id, user_id,
                tx_date, amount, description, merchant, original_category,
                classification, reason, created_at
            FROM mvp_transactions
            WHERE organization_id = ?
        """
        params: List[Any] = [org_id]

        if upload_id:
            query += " AND upload_id = ?"
            params.append(upload_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

    return {
        "organization_id": org_id,
        "upload_id": upload_id,
        "transactions": [dict(r) for r in rows],
    }


@router.get("/insights")
async def insights(
    upload_id: Optional[str] = None,
    org_id: str = Depends(_resolve_mvp_org_id),
    identity: AuthIdentity = Depends(get_current_identity),
):
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        where = "organization_id = ?"
        params: List[Any] = [org_id]
        if upload_id:
            where += " AND upload_id = ?"
            params.append(upload_id)

        totals = conn.execute(
            f"""
            SELECT
                classification,
                COUNT(*) as count,
                SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) as outflow,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as inflow
            FROM mvp_transactions
            WHERE {where}
            GROUP BY classification
            """,
            params,
        ).fetchall()

        overall = conn.execute(
            f"""
            SELECT
                COUNT(*) as total_transactions,
                SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) as total_outflow,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_inflow
            FROM mvp_transactions
            WHERE {where}
            """,
            params,
        ).fetchone()

    by_class = {r["classification"]: {"count": r["count"], "outflow": r["outflow"] or 0, "inflow": r["inflow"] or 0} for r in totals}
    total_outflow = float(overall["total_outflow"] or 0)
    total_inflow = float(overall["total_inflow"] or 0)

    return {
        "organization_id": org_id,
        "upload_id": upload_id,
        "total_transactions": int(overall["total_transactions"] or 0),
        "total_outflow": total_outflow,
        "total_inflow": total_inflow,
        "net": total_inflow - total_outflow,
        "by_classification": by_class,
    }


@router.get("/export")
async def export_csv(
    upload_id: Optional[str] = None,
    org_id: str = Depends(_resolve_mvp_org_id),
    identity: AuthIdentity = Depends(get_current_identity),
):
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT
                tx_date, amount, description, merchant, original_category,
                classification, reason, upload_id
            FROM mvp_transactions
            WHERE organization_id = ?
        """
        params: List[Any] = [org_id]
        if upload_id:
            query += " AND upload_id = ?"
            params.append(upload_id)
        query += " ORDER BY tx_date ASC, created_at ASC"

        rows = conn.execute(query, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "amount", "description", "merchant", "original_category", "classification", "reason", "upload_id"])
    for r in rows:
        writer.writerow(
            [
                r["tx_date"],
                r["amount"],
                r["description"],
                r["merchant"],
                r["original_category"],
                r["classification"],
                r["reason"],
                r["upload_id"],
            ]
        )

    filename = "export.csv" if not upload_id else f"export-{upload_id}.csv"
    stream = io.BytesIO(output.getvalue().encode("utf-8"))

    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

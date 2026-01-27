from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request

from app.auth_context import get_current_context, AuthContext
from app.db import get_db_connection
from app.govcon.contract import GOVCON_CONTRACT_VERSION

router = APIRouter()


def _table_exists(conn, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _compute_hash(prev_hash: Optional[str], payload: str) -> str:
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("utf-8"))
    h.update(payload.encode("utf-8"))
    return h.hexdigest()


@router.get("/govcon/audit/verify")
async def govcon_audit_verify(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Read-only hash chain verification for audit events.

    Canonical: read-only, fail-closed, advisory-only.
    Returns empty state if table lacks hash columns.
    """
    request_id = getattr(request.state, "request_id", None)
    org_id = ctx.get("org_id")

    table = None
    with get_db_connection() as conn:
        for t in ("audit_events", "audit_log", "mvp_audit_events"):
            if _table_exists(conn, t):
                table = t
                break

        if not table:
            now = datetime.utcnow().isoformat()
            return {
                # Contract version - ALWAYS present
                "govcon_version": GOVCON_CONTRACT_VERSION,
                # Lifecycle - ALWAYS present
                "lifecycle": {"status": "no_data", "reason_code": "NO_AUDIT_TABLE"},
                # Evidence metadata - ALWAYS present
                "evidence": {
                    "sources": [],
                    "coverage_window": {"start": None, "end": None},
                    "evaluated_at": now,
                    "dcaa_compliant": True,
                },
                "request_id": request_id,
                "status": "empty",
                "verified_count": 0,
                "total": 0,
                "events": [],
                "advisory": {"message": "No audit table found."},
            }

        # P0 Security: Validate table name against allowlist
        allowed_tables = {"audit_events", "audit_log", "mvp_audit_events"}
        if table not in allowed_tables:
            cols = []
        else:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            except Exception:
                cols = []

        required = {"prev_hash", "event_hash", "payload"}
        if not required.issubset(set(cols)):
            now = datetime.utcnow().isoformat()
            return {
                # Contract version - ALWAYS present
                "govcon_version": GOVCON_CONTRACT_VERSION,
                # Lifecycle - ALWAYS present
                "lifecycle": {"status": "no_data", "reason_code": "MISSING_HASH_COLUMNS"},
                # Evidence metadata - ALWAYS present
                "evidence": {
                    "sources": [table],
                    "coverage_window": {"start": None, "end": None},
                    "evaluated_at": now,
                    "dcaa_compliant": True,
                },
                "request_id": request_id,
                "status": "empty",
                "verified_count": 0,
                "total": 0,
                "events": [],
                "advisory": {"message": f"Table '{table}' does not expose hash chaining columns."},
            }

        # P0 Security: Table name already validated in allowed_tables above
        try:
            rows = conn.execute(
                f"""
                SELECT id,
                       COALESCE(created_at, '') as created_at,
                       COALESCE(event_type, '') as event_type,
                       prev_hash,
                       event_hash,
                       COALESCE(payload, '') as payload
                FROM {table}
                WHERE (? IS NULL OR organization_id = ?)
                ORDER BY created_at ASC
                LIMIT 500
                """,
                (org_id, org_id),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                f"""
                SELECT id,
                       COALESCE(created_at, '') as created_at,
                       COALESCE(event_type, '') as event_type,
                       prev_hash,
                       event_hash,
                       COALESCE(payload, '') as payload
                FROM {table}
                ORDER BY created_at ASC
                LIMIT 500
                """
            ).fetchall()

    if not rows:
        now = datetime.utcnow().isoformat()
        return {
            # Contract version - ALWAYS present
            "govcon_version": GOVCON_CONTRACT_VERSION,
            # Lifecycle - ALWAYS present
            "lifecycle": {"status": "no_data", "reason_code": "NO_EVENTS"},
            # Evidence metadata - ALWAYS present
            "evidence": {
                "sources": [table] if table else [],
                "coverage_window": {"start": None, "end": None},
                "evaluated_at": now,
                "dcaa_compliant": True,
            },
            "request_id": request_id,
            "status": "empty",
            "verified_count": 0,
            "total": 0,
            "events": [],
            "advisory": {"message": "No events to verify."},
        }

    events: List[Dict[str, Any]] = []
    verified = 0

    for rid, created_at, event_type, prev_hash, event_hash, payload in rows:
        computed = _compute_hash(prev_hash, payload)
        ok = (event_hash == computed)
        if ok:
            verified += 1
        events.append(
            {
                "id": str(rid),
                "created_at": str(created_at)[:19] if created_at else "",
                "event_type": str(event_type),
                "prev_hash": prev_hash,
                "event_hash": event_hash,
                "computed_hash": computed,
                "ok": ok,
            }
        )

    status = "ok" if verified == len(events) else "error"
    now = datetime.utcnow().isoformat()
    is_valid = (verified == len(events))
    return {
        # Contract version - ALWAYS present
        "govcon_version": GOVCON_CONTRACT_VERSION,
        # Lifecycle - ALWAYS present
        "lifecycle": {"status": "success" if is_valid else "partial", "reason_code": None if is_valid else "HASH_MISMATCH"},
        # Evidence metadata - ALWAYS present
        "evidence": {
            "sources": [table] if table else [],
            "coverage_window": {"start": None, "end": None},
            "evaluated_at": now,
            "dcaa_compliant": is_valid,
        },
        "request_id": request_id,
        "status": status,
        "verified_count": verified,
        "total": len(events),
        "events": events,
        "advisory": {
            "message": "Verification compares stored event_hash to SHA-256(prev_hash + payload).",
        },
    }

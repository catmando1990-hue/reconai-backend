from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from app.auth_context import get_current_context
from app.db import get_db_connection

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
def govcon_audit_verify(request: Request) -> Dict[str, Any]:
    """
    Read-only hash chain verification for audit events.

    Canonical: read-only, fail-closed, advisory-only.
    Returns empty state if table lacks hash columns.
    """
    ctx = get_current_context()
    request_id = getattr(request.state, "request_id", None)
    org_id = ctx.get("org_id")

    table = None
    with get_db_connection() as conn:
        for t in ("audit_events", "audit_log", "mvp_audit_events"):
            if _table_exists(conn, t):
                table = t
                break

        if not table:
            return {
                "request_id": request_id,
                "status": "empty",
                "verified_count": 0,
                "total": 0,
                "events": [],
                "advisory": {"message": "No audit table found."},
            }

        try:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        except Exception:
            cols = []

        required = {"prev_hash", "event_hash", "payload"}
        if not required.issubset(set(cols)):
            return {
                "request_id": request_id,
                "status": "empty",
                "verified_count": 0,
                "total": 0,
                "events": [],
                "advisory": {"message": f"Table '{table}' does not expose hash chaining columns."},
            }

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
        return {
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
    return {
        "request_id": request_id,
        "status": status,
        "verified_count": verified,
        "total": len(events),
        "events": events,
        "advisory": {
            "message": "Verification compares stored event_hash to SHA-256(prev_hash + payload).",
        },
    }

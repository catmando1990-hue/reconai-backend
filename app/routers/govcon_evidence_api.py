from __future__ import annotations

from typing import Any, Dict, List
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


@router.get("/govcon/evidence")
def govcon_evidence(request: Request) -> Dict[str, Any]:
    """
    Read-only evidence index for audit artifacts.

    Canonical: read-only, fail-closed, advisory-only.
    Returns empty list if no audit table exists.
    """
    ctx = get_current_context()
    request_id = getattr(request.state, "request_id", None)
    org_id = ctx.get("org_id")

    items: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            for tbl in ("audit_events", "audit_log", "mvp_audit_events"):
                if not _table_exists(conn, tbl):
                    continue

                try:
                    rows = conn.execute(
                        f"""
                        SELECT id,
                               COALESCE(created_at, '') as created_at,
                               COALESCE(event_type, '') as event_type,
                               COALESCE(payload, '') as payload,
                               COALESCE(event_hash, NULL) as event_hash
                        FROM {tbl}
                        WHERE (? IS NULL OR organization_id = ?)
                        ORDER BY created_at DESC
                        LIMIT 200
                        """,
                        (org_id, org_id),
                    ).fetchall()
                except Exception:
                    rows = conn.execute(
                        f"""
                        SELECT id,
                               COALESCE(created_at, '') as created_at,
                               COALESCE(event_type, '') as event_type,
                               COALESCE(payload, '') as payload,
                               COALESCE(event_hash, NULL) as event_hash
                        FROM {tbl}
                        ORDER BY created_at DESC
                        LIMIT 200
                        """
                    ).fetchall()

                for rid, created_at, event_type, payload, event_hash in rows:
                    items.append(
                        {
                            "id": str(rid),
                            "created_at": str(created_at)[:19] if created_at else "",
                            "type": "audit_event",
                            "title": event_type or "audit_event",
                            "hash": event_hash,
                            "source": tbl,
                        }
                    )

                break
    except Exception:
        items = []

    return {
        "request_id": request_id,
        "items": items,
        "advisory": {
            "message": "Evidence index is read-only. If no audit table is present, this will be empty.",
        },
    }
